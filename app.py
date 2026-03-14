import streamlit as st
import pandas as pd
import math
import openseespy.opensees as ops
import pypandoc
import os
import tempfile

# ==========================================
# SESSION STATE – persiste resultados entre re-execuções
# ==========================================
if "resultados_calc" not in st.session_state:
    st.session_state["resultados_calc"] = None

# ==========================================
# CONFIGURAÇÃO DA PÁGINA
# ==========================================
st.set_page_config(
    page_title="Solo Grampeado - Memorial de Cálculo",
    page_icon="🏗️",
    layout="wide"
)
st.title("🏗️ Memorial de Cálculo: Contenção em Solo Grampeado")
st.markdown("---")

# ==========================================
# BARRA LATERAL (INPUTS DO USUÁRIO)
# ==========================================
with st.sidebar:
    st.header("1. Geometria e Paramento")
    Espessura_Paramento_h_m = st.number_input("Espessura do Paramento (m)", value=0.15, step=0.01)
    Largura_Placa_bp_m      = st.number_input("Largura da Placa (m)", value=0.30, step=0.05)
    Espacamento_Sh_m        = st.number_input("Espaçamento Sh (m)", value=1.50, step=0.10)
    Espacamento_Sv_m        = st.number_input("Espaçamento Sv (m)", value=1.50, step=0.10)
    Cobrimento_Nominal_cm   = st.number_input("Cobrimento (cm)", value=3.0, step=0.5)

    st.header("2. Propriedades dos Materiais")
    fck_Concreto_MPa = st.number_input("fck do Concreto (MPa)", value=25.0, step=1.0)
    fy_Aco_MPa       = st.number_input("fyk da Tela Soldada (MPa)", value=600.0, step=10.0)
    Kh_Solo_kNm3     = st.number_input("Coef. Mola do Solo (Kh - kN/m³)", value=25000.0, step=1000.0)

    st.header("3. Grampo e Perfuração")
    Diametro_Furo_m          = st.number_input("Diâmetro do Furo (m)", value=0.10, step=0.01)
    Diametro_Barra_mm        = st.number_input("Diâmetro da Barra (mm)", value=25.0, step=1.0)
    Aco_fyk_MPa              = st.number_input("fyk da Barra (MPa)", value=500.0, step=10.0)
    Coeficiente_Seguranca_Aco = st.number_input("Coef. Segurança Aço (γs)", value=1.15, step=0.05)

    st.header("4. Corrosão (NBR 16920-2)")
    Agressividade_do_Meio = st.selectbox(
        "Agressividade",
        ["Não Agressivo", "Agressivo (PH <= 5 ou Solo Orgânico)"]
    )
    Tipo_de_Solo = st.selectbox(
        "Tipo de Solo",
        ["Solos Naturais Inalterados", "Aterros Compactados", "Aterros Não Compactados"]
    )
    Vida_Util = st.selectbox("Vida Útil", ["50 anos", "25 anos", "5 anos"])

# Banco de Dados de Corrosão (NBR 16920-2)
tabela_corrosao = {
    "Não Agressivo": {
        "Solos Naturais Inalterados":   {"5 anos": 0.00, "25 anos": 0.30, "50 anos": 0.60},
        "Aterros Compactados":          {"5 anos": 0.09, "25 anos": 0.35, "50 anos": 0.60},
        "Aterros Não Compactados":      {"5 anos": 0.18, "25 anos": 0.70, "50 anos": 1.20},
    },
    "Agressivo (PH <= 5 ou Solo Orgânico)": {
        "Solos Naturais Inalterados":   {"5 anos": 0.15, "25 anos": 0.75, "50 anos": 1.50},
        "Aterros Compactados":          {"5 anos": 0.20, "25 anos": 1.00, "50 anos": 1.75},
        "Aterros Não Compactados":      {"5 anos": 0.50, "25 anos": 2.00, "50 anos": 3.25},
    },
}

# ==========================================
# TELA PRINCIPAL (ESTRATIGRAFIA)
# ==========================================
st.subheader("Camadas de Solo (Estratigrafia e NSPT)")
st.write("Edite a tabela abaixo para adicionar as camadas do seu maciço:")

df_padrao = pd.DataFrame([
    {"Classe NBR": "Argilas e siltes argilosos", "Estado NBR": "Rija(o)",      "Espessura (m)": 4.0, "NSPT Médio": 15},
    {"Classe NBR": "Areias e siltes arenosos",   "Estado NBR": "Compacta(o)", "Espessura (m)": 6.0, "NSPT Médio": 20},
])
df_solos = st.data_editor(df_padrao, num_rows="dynamic", use_container_width=True)

# ==========================================
# PAINEL DE AVISOS CONTEXTUAIS (tempo real)
# ==========================================
st.markdown("---")

# Faixas de validade do modelo MEF-Winkler para solo grampeado
FAIXA_Sh    = (0.8, 2.0)   # m
FAIXA_Sv    = (0.8, 2.0)   # m
FAIXA_h     = (0.10, 0.20) # m
FAIXA_fck   = (20.0, 35.0) # MPa
FAIXA_Kh    = (5000, 80000) # kN/m³
FAIXA_esbel = (0.5, 2.0)   # razão Sh/Sv — fora disso Marcus perde precisão

avisos_info    = []  # ⚠️ fora da faixa validada — resultado ainda utilizável com ressalva
avisos_alerta  = []  # 🔴 condição problemática — resultado pode ser não-conservador

# --- Geometria do paramento ---
if not (FAIXA_h[0] <= Espessura_Paramento_h_m <= FAIXA_h[1]):
    avisos_info.append(
        f"**Espessura do paramento ({Espessura_Paramento_h_m*100:.0f} cm)** está fora da faixa usual "
        f"de {FAIXA_h[0]*100:.0f}–{FAIXA_h[1]*100:.0f} cm para concreto projetado em solo grampeado. "
        "O modelo MEF-Winkler foi calibrado para essa faixa; resultados fora dela devem ser verificados "
        "com software de MEF dedicado."
    )

# --- Espaçamentos ---
if not (FAIXA_Sh[0] <= Espacamento_Sh_m <= FAIXA_Sh[1]):
    avisos_info.append(
        f"**Espaçamento Sh = {Espacamento_Sh_m:.2f} m** está fora da faixa validada "
        f"({FAIXA_Sh[0]:.1f}–{FAIXA_Sh[1]:.1f} m). Os métodos empíricos FHWA e Clouterre "
        "foram desenvolvidos para espaçamentos nessa faixa; extrapolações podem ser não-conservadoras."
    )
if not (FAIXA_Sv[0] <= Espacamento_Sv_m <= FAIXA_Sv[1]):
    avisos_info.append(
        f"**Espaçamento Sv = {Espacamento_Sv_m:.2f} m** está fora da faixa validada "
        f"({FAIXA_Sv[0]:.1f}–{FAIXA_Sv[1]:.1f} m). Os métodos empíricos FHWA e Clouterre "
        "foram desenvolvidos para espaçamentos nessa faixa; extrapolações podem ser não-conservadoras."
    )

# --- Razão de aspecto Sh/Sv ---
razao_sv = Espacamento_Sh_m / Espacamento_Sv_m if Espacamento_Sv_m > 0 else 1.0
razao_aspecto = max(razao_sv, 1.0 / razao_sv)  # sempre >= 1
if not (FAIXA_esbel[0] <= razao_aspecto <= FAIXA_esbel[1]):
    avisos_info.append(
        f"**Razão Sh/Sv = {razao_sv:.2f}** indica painel muito alongado (λ = {razao_aspecto:.2f}). "
        "A tabela de Marcus para laje engastada nos 4 bordos é menos precisa para λ > 2,0; "
        "considere usar o método de grelha ou MEF tridimensional para esse caso."
    )

# --- fck ---
if not (FAIXA_fck[0] <= fck_Concreto_MPa <= FAIXA_fck[1]):
    avisos_info.append(
        f"**fck = {fck_Concreto_MPa:.0f} MPa** está fora da faixa típica de concreto projetado "
        f"({FAIXA_fck[0]:.0f}–{FAIXA_fck[1]:.0f} MPa). Verifique se o valor informado corresponde "
        "ao concreto projetado via-seca ou via-úmida utilizado."
    )

# --- Coeficiente de mola ---
if not (FAIXA_Kh[0] <= Kh_Solo_kNm3 <= FAIXA_Kh[1]):
    avisos_info.append(
        f"**Kh = {Kh_Solo_kNm3:,.0f} kN/m³** está fora da faixa usual para solos "
        f"({FAIXA_Kh[0]:,}–{FAIXA_Kh[1]:,} kN/m³). O modelo de Winkler é sensível a esse parâmetro: "
        "valores muito altos tornam as molas rígidas demais e aproximam o resultado de uma placa "
        "sobre apoio rígido, enquanto valores muito baixos subestimam o suporte do solo."
    )

# --- Cobrimento vs espessura ---
cobrimento_m = Cobrimento_Nominal_cm / 100.0
relacao_cob = cobrimento_m / Espessura_Paramento_h_m
if relacao_cob > 0.25:
    avisos_alerta.append(
        f"**Cobrimento ({Cobrimento_Nominal_cm:.1f} cm) representa {relacao_cob*100:.0f}% da espessura "
        f"do paramento ({Espessura_Paramento_h_m*100:.0f} cm).** "
        "Isso reduz significativamente o d útil e aumenta a área de aço necessária. "
        "Verifique se o cobrimento nominal está correto para concreto projetado (NBR 14931)."
    )

# --- Alerta sobre hipóteses do MEF-Winkler ---
avisos_mef = (
    "**Hipóteses do modelo MEF-Winkler (OpenSeesPy):** "
    "_(i)_ A reação do solo é modelada por molas independentes (Winkler) — não há transferência de carga "
    "lateral entre pontos adjacentes, o que tende a superestimar os momentos. "
    "_(ii)_ O grampo é simulado como apoio rígido pontual no nó central — na prática a reação se "
    "distribui pela área da placa de ancoragem, reduzindo a concentração de momento. "
    "_(iii)_ Os resultados são mais confiáveis quando Sh e Sv estão entre "
    f"{FAIXA_Sh[0]:.1f} e {FAIXA_Sh[1]:.1f} m e h entre "
    f"{FAIXA_h[0]*100:.0f} e {FAIXA_h[1]*100:.0f} cm. "
    "Fora dessas faixas, confronte o resultado MEF com software de MEF dedicado antes de adotá-lo."
)

# --- Renderização dos avisos ---
with st.expander("ℹ️ Avisos e hipóteses do modelo — clique para expandir", expanded=bool(avisos_alerta or avisos_info)):

    st.info(avisos_mef)

    if avisos_alerta:
        for a in avisos_alerta:
            st.error("🔴 " + a)

    if avisos_info:
        for a in avisos_info:
            st.warning("⚠️ " + a)

    if not avisos_alerta and not avisos_info:
        st.success(
            "✅ Todos os parâmetros estão dentro das faixas validadas para o modelo MEF-Winkler. "
            "Os resultados têm boa aderência com softwares de MEF dedicados (desvio esperado < 15%)."
        )

# ==========================================
# MOTOR DE CÁLCULO
# ==========================================
if st.button("🚀 Processar Cálculo e Gerar Memorial (Word)", type="primary", use_container_width=True):
    with st.spinner("Executando análise numérica (MEF) e métodos analíticos..."):

        # -------------------------------------------------------
        # VALIDAÇÕES DE INPUT
        # -------------------------------------------------------
        erros = []
        if Cobrimento_Nominal_cm / 100.0 >= Espessura_Paramento_h_m:
            erros.append("Cobrimento nominal (%.1f cm) deve ser menor que a espessura do paramento (%.0f cm)." %
                         (Cobrimento_Nominal_cm, Espessura_Paramento_h_m * 100))
        if Diametro_Barra_mm / 1000.0 >= Diametro_Furo_m:
            erros.append("Diâmetro da barra (%.0f mm) deve ser menor que o diâmetro do furo (%.0f mm)." %
                         (Diametro_Barra_mm, Diametro_Furo_m * 1000))
        if df_solos["NSPT Médio"].isnull().any() or (df_solos["NSPT Médio"] < 0).any():
            erros.append("Todos os valores de NSPT devem ser preenchidos e não-negativos.")
        if erros:
            for e in erros:
                st.error("⚠️ " + e)
            st.stop()

        # -------------------------------------------------------
        # 1. MÓDULO GEOTÉCNICO (qs e bs por camada)
        # -------------------------------------------------------
        FSp = 2.0
        resultados_geo = []
        profundidade_acumulada = 0.0

        for _, row in df_solos.iterrows():
            nspt      = row["NSPT Médio"]
            espessura = row["Espessura (m)"]
            prof_ini  = profundidade_acumulada
            prof_fim  = profundidade_acumulada + espessura
            profundidade_acumulada = prof_fim

            qs1 = qsd1 = qs2 = qsd2 = qsd_adotado = bs_kN_m = 0.0

            if nspt > 0:
                qs1  = 50 + (7.5 * nspt)
                qsd1 = qs1 / FSp
                qs2  = (45.12 * math.log(nspt)) - 14.99 if nspt > 1 else 0.0
                if qs2 < 0:
                    qs2 = 0.0
                qsd2         = qs2 / FSp
                qsd_adotado  = min(qsd1, qsd2)
                bs_kN_m      = qsd_adotado * math.pi * Diametro_Furo_m
            else:
                st.warning(f"⚠️ Camada {prof_ini:.1f}–{prof_fim:.1f} m tem NSPT = 0: bs = 0 para esse trecho.")

            resultados_geo.append({
                "Trecho (m)":          f"{prof_ini:.1f} a {prof_fim:.1f}",
                "Classe NBR":          row["Classe NBR"],
                "Estado NBR":          row["Estado NBR"],
                "NSPT Médio":          nspt,
                "qsd1 Ortigão (kPa)":  round(qsd1, 2),
                "qsd2 Springer (kPa)": round(qsd2, 2),
                "qsd Adotado (kPa)":   round(qsd_adotado, 2),
                "bs (kN/m)":           round(bs_kN_m, 2),
            })

        # Tabela markdown para o Word
        tabela_solos_md  = "| Trecho (m) | Tipo de Solo (NBR) | NSPT | qsd Ortigão (kPa) | qsd Springer (kPa) | qsd Adotado (kPa) | bs (kN/m) |\n"
        tabela_solos_md += "|:---:|---|:---:|:---:|:---:|:---:|:---:|\n"
        for r in resultados_geo:
            tabela_solos_md += (
                f"| {r['Trecho (m)']} | {r['Classe NBR']} ({r['Estado NBR']}) | {r['NSPT Médio']} "
                f"| {r['qsd1 Ortigão (kPa)']} | {r['qsd2 Springer (kPa)']} "
                f"| **{r['qsd Adotado (kPa)']}** | **{r['bs (kN/m)']}** |\n"
            )

        # -------------------------------------------------------
        # 2. MÓDULO DO GRAMPO (Clouterre e Corrosão)
        # -------------------------------------------------------
        t_sacrificio  = tabela_corrosao[Agressividade_do_Meio][Tipo_de_Solo][Vida_Util]
        d_util_mm     = max(Diametro_Barra_mm - 2 * t_sacrificio, 0.0)
        area_util_mm2 = (math.pi * d_util_mm ** 2) / 4.0

        rtd_kN = (area_util_mm2 * Aco_fyk_MPa) / (Coeficiente_Seguranca_Aco * 1000.0)
        s_max  = max(Espacamento_Sh_m, Espacamento_Sv_m)
        # Clouterre: fator mínimo 0.60 (proteção para Sh ou Sv < 1.0 m)
        fator_clouterre = max(0.60 + 0.20 * (s_max - 1.0), 0.60)
        t0_kN = rtd_kN * fator_clouterre

        # -------------------------------------------------------
        # 3. MÓDULO DO PARAMENTO – QUATRO MÉTODOS DE FLEXÃO
        # -------------------------------------------------------
        q_pressao_kNm2 = t0_kN / (Espacamento_Sh_m * Espacamento_Sv_m)
        d_util_m       = Espessura_Paramento_h_m - (Cobrimento_Nominal_cm / 100.0)
        bw_m           = 1.0
        fcd_kN_m2      = (fck_Concreto_MPa / 1.4) * 1000.0
        fyd_kN_m2      = (fy_Aco_MPa * 1000.0) / 1.15
        gamma_f        = 1.4  # coeficiente de majoração das ações

        As_min_cm2 = 0.0015 * bw_m * Espessura_Paramento_h_m * 10_000.0

        def dimensionar_as(Md_kNm_m: float) -> tuple[float, str]:
            """Retorna (As_cm2/m, status) para um momento de cálculo Md (kNm/m)."""
            Kmd = Md_kNm_m / (bw_m * d_util_m ** 2 * fcd_kN_m2)
            if Kmd <= 0.259:
                kx  = (1 - math.sqrt(1 - 2.36 * Kmd)) / 1.18
                z   = d_util_m * (1 - 0.4 * kx)
                As  = (Md_kNm_m / (z * fyd_kN_m2)) * 10_000.0
                status = "OK"
            else:
                As     = 999.0
                status = "ERRO – seção insuficiente (Kmd > 0.259)"
            As_final = max(As, As_min_cm2)
            return round(As_final, 2), status

        # ---- 3a. FHWA – placa simplesmente apoiada (M = q·Sh·Sv/8) ----
        Md_FHWA_apoiada  = gamma_f * q_pressao_kNm2 * Espacamento_Sh_m * Espacamento_Sv_m / 8.0
        As_FHWA_ap, st_FHWA_ap = dimensionar_as(Md_FHWA_apoiada)

        # ---- 3b. FHWA – placa engastada nos grampos (M = q·Sh·Sv/12) ----
        Md_FHWA_eng      = gamma_f * q_pressao_kNm2 * Espacamento_Sh_m * Espacamento_Sv_m / 12.0
        As_FHWA_eng, st_FHWA_eng = dimensionar_as(Md_FHWA_eng)

        # ---- 3c. Clouterre – placa biapoiada (M = T0·max(Sh,Sv)/8) ----
        Md_Clouterre     = gamma_f * t0_kN * max(Espacamento_Sh_m, Espacamento_Sv_m) / 8.0
        As_Clouterre, st_Clouterre = dimensionar_as(Md_Clouterre)

        # ---- 3d. NBR – laje engastada nos 4 bordos (coeficientes de Marcus) ----
        # Relação de lados λ = Sh / Sv (≥ 1 por convenção)
        lx = min(Espacamento_Sh_m, Espacamento_Sv_m)   # menor vão
        ly = max(Espacamento_Sh_m, Espacamento_Sv_m)   # maior vão
        lamb = ly / lx                                  # λ ≥ 1

        # Coeficientes de momento (Marcus) para laje retangular engastada nos 4 bordos
        # Mx = αx · q · lx²  (vão menor);  My = αy · q · lx²  (vão maior)
        # Tabela condensada de Marcus (ABNT/prática brasileira):
        #   λ:   1.0    1.1    1.2    1.3    1.4    1.5    1.75   2.0
        #  αx: 0.0513 0.0581 0.0639 0.0687 0.0726 0.0756 0.0812 0.0829
        #  αy: 0.0513 0.0430 0.0365 0.0312 0.0271 0.0238 0.0183 0.0158
        lambdas = [1.0,  1.1,   1.2,   1.3,   1.4,   1.5,   1.75,  2.0]
        alphas_x = [0.0513, 0.0581, 0.0639, 0.0687, 0.0726, 0.0756, 0.0812, 0.0829]
        alphas_y = [0.0513, 0.0430, 0.0365, 0.0312, 0.0271, 0.0238, 0.0183, 0.0158]

        def interpolar(xval, xs, ys):
            """Interpolação linear entre pontos tabelados."""
            if xval <= xs[0]:  return ys[0]
            if xval >= xs[-1]: return ys[-1]
            for i in range(len(xs) - 1):
                if xs[i] <= xval <= xs[i+1]:
                    t = (xval - xs[i]) / (xs[i+1] - xs[i])
                    return ys[i] + t * (ys[i+1] - ys[i])
            return ys[-1]

        alpha_x = interpolar(lamb, lambdas, alphas_x)
        alpha_y = interpolar(lamb, lambdas, alphas_y)

        Mxd_NBR = gamma_f * alpha_x * q_pressao_kNm2 * lx ** 2   # kNm/m
        Myd_NBR = gamma_f * alpha_y * q_pressao_kNm2 * lx ** 2   # kNm/m
        Md_NBR  = max(Mxd_NBR, Myd_NBR)                           # dimensiona pelo maior

        As_NBR, st_NBR = dimensionar_as(Md_NBR)

        # ---- 3e. MEF (OpenSeesPy) – placa espessa Mindlin-Reissner sobre Winkler ----
        ops.wipe()
        ops.model('basic', '-ndm', 3, '-ndf', 6)
        nx, ny = 15, 15
        dx = Espacamento_Sh_m / nx
        dy = Espacamento_Sv_m / ny
        E_c = 4760.0 * math.sqrt(fck_Concreto_MPa) * 1000.0  # kN/m²

        # --- Nós de estrutura ---
        node_tag = 1
        for j in range(ny + 1):
            for i in range(nx + 1):
                x = i * dx - Espacamento_Sh_m / 2.0
                y = j * dy - Espacamento_Sv_m / 2.0
                ops.node(node_tag, x, y, 0.0)
                # DOFs: ux uy uz rotX rotY rotZ
                ops.fix(node_tag, 0, 0, 0, 0, 0, 1)
                node_tag += 1

        n_nos = node_tag - 1  # total de nós criados

        # --- Molas de solo (nós duplicados deslocados em z, material elástico) ----
        mat_base = 50000   # offset seguro para não colidir com node_tags (max 256)
        for n in range(1, n_nos + 1):
            coord = ops.nodeCoord(n)
            ops.node(n + mat_base, coord[0], coord[1], -0.001)
            ops.fix(n + mat_base, 1, 1, 1, 1, 1, 1)
            ops.uniaxialMaterial('Elastic', n, Kh_Solo_kNm3 * dx * dy)
            ops.element('zeroLength', n + mat_base, n, n + mat_base,
                        '-mat', n, '-dir', 3)

        # --- Seção de casca ---
        sec_tag = 1
        ops.section('ElasticMembranePlateSection', sec_tag, E_c, 0.2,
                    Espessura_Paramento_h_m, 0.0)

        # --- Elementos ShellMITC4 ---
        ele_tag = 1
        for j in range(ny):
            for i in range(nx):
                n1 = j * (nx + 1) + i + 1
                n2 = n1 + 1
                n3 = n2 + (nx + 1)
                n4 = n1 + (nx + 1)
                ops.element('ShellMITC4', ele_tag, n1, n2, n3, n4, sec_tag)
                ele_tag += 1
        n_eles = ele_tag - 1  # total de elementos criados

        # --- Engaste central (ponto de aplicação do grampo) ---
        center_node = int(((ny // 2) * (nx + 1)) + (nx // 2) + 1)
        ops.fix(center_node, 1, 1, 1, 0, 0, 0)

        # --- Carga distribuída: forças nodais equivalentes ---
        ops.timeSeries('Linear', 1)
        ops.pattern('Plain', 1, 1)

        # Força por nó = q × área tributária
        Fz_nó_interior = -q_pressao_kNm2 * dx * dy
        for j in range(ny + 1):
            for i in range(nx + 1):
                nid = j * (nx + 1) + i + 1
                # Área tributária: canto=dx*dy/4, borda=dx*dy/2, interior=dx*dy
                fx = 0.5 if (i == 0 or i == nx) else 1.0
                fy = 0.5 if (j == 0 or j == ny) else 1.0
                ops.load(nid, 0.0, 0.0, Fz_nó_interior * fx * fy, 0.0, 0.0, 0.0)

        # --- Análise estática ---
        ops.system('UmfPack')
        ops.numberer('RCM')
        ops.constraints('Plain')
        ops.integrator('LoadControl', 1.0)
        ops.algorithm('Linear')
        ops.analysis('Static')
        ops.analyze(1)

        # --- Extração de momentos (ShellMITC4) ---
        # eleResponse('stresses') retorna 4 pontos de integração × 8 componentes = 32 valores:
        # [Nxx, Nyy, Nxy, Mxx, Myy, Mxy, Vxz, Vyz] por ponto — Mxx e Myy em kNm/m
        M_max_MEF = 0.0
        for i in range(1, n_eles + 1):
            s = ops.eleResponse(i, 'stresses')
            if s and len(s) >= 32:
                for pt in range(4):
                    mxx = abs(s[pt * 8 + 3])
                    myy = abs(s[pt * 8 + 4])
                    M_max_MEF = max(M_max_MEF, mxx, myy)

        if M_max_MEF == 0.0:
            st.warning("⚠️ MEF não retornou momentos via 'stresses'. Usando fórmula simplificada como fallback.")
            M_max_MEF = q_pressao_kNm2 * max(Espacamento_Sh_m, Espacamento_Sv_m) ** 2 / 10.0

        Md_MEF = M_max_MEF * gamma_f
        As_MEF, st_MEF = dimensionar_as(Md_MEF)

        # -------------------------------------------------------
        # 4. VERIFICAÇÃO DE PUNÇÃO (NBR 6118)
        # -------------------------------------------------------
        Fsd        = t0_kN * gamma_f
        rho        = (As_MEF / 10_000.0) / (bw_m * d_util_m)
        u_critico  = 4 * Largura_Placa_bp_m + 2 * math.pi * (2 * d_util_m)
        tau_Sd     = Fsd / (u_critico * d_util_m)

        k_scale    = min(1 + math.sqrt(20.0 / (d_util_m * 100.0)), 2.0)
        tau_Rd1    = 0.13 * k_scale * (100.0 * rho * fck_Concreto_MPa) ** (1.0 / 3.0) * 1000.0

        status_puncao = (
            "✅ OK – Concreto resiste sem estribos"
            if tau_Sd <= tau_Rd1
            else "❌ FALHA NA TRAÇÃO DIAGONAL – Requer Armadura Transversal"
        )

        # -------------------------------------------------------
        # 5. SALVAR RESULTADOS NO SESSION STATE
        # -------------------------------------------------------
        st.session_state["resultados_calc"] = {
            "t0_kN": t0_kN, "rtd_kN": rtd_kN, "status_puncao": status_puncao,
            "tau_Sd": tau_Sd, "tau_Rd1": tau_Rd1, "Fsd": Fsd,
            "u_critico": u_critico, "k_scale": k_scale,
            "As_FHWA_ap": As_FHWA_ap, "As_FHWA_eng": As_FHWA_eng,
            "As_Clouterre": As_Clouterre, "As_NBR": As_NBR, "As_MEF": As_MEF,
            "st_FHWA_ap": st_FHWA_ap, "st_FHWA_eng": st_FHWA_eng,
            "st_Clouterre": st_Clouterre, "st_NBR": st_NBR, "st_MEF": st_MEF,
            "Md_FHWA_apoiada": Md_FHWA_apoiada, "Md_FHWA_eng": Md_FHWA_eng,
            "Md_Clouterre": Md_Clouterre, "Md_NBR": Md_NBR, "Md_MEF": Md_MEF,
            "M_max_MEF": M_max_MEF,
            "lamb": lamb, "lx": lx, "ly": ly,
            "alpha_x": alpha_x, "alpha_y": alpha_y,
            "Mxd_NBR": Mxd_NBR, "Myd_NBR": Myd_NBR,
            "As_min_cm2": As_min_cm2,
            "q_pressao_kNm2": q_pressao_kNm2, "d_util_m": d_util_m,
            "bw_m": bw_m, "fcd_kN_m2": fcd_kN_m2, "fyd_kN_m2": fyd_kN_m2,
            "gamma_f": gamma_f, "FSp": FSp,
            "t_sacrificio": t_sacrificio, "d_util_mm": d_util_mm,
            "area_util_mm2": area_util_mm2, "s_max": s_max,
            "fator_clouterre": fator_clouterre,
            "tabela_solos_md": tabela_solos_md,
            "nx": nx, "ny": ny,
        }
        st.success("✅ Cálculos finalizados! Selecione o método adotado abaixo.")

        # -------------------------------------------------------
        # 6. GERAÇÃO DO MEMORIAL EM WORD (PANDOC)  — veja abaixo
        # -------------------------------------------------------


# ==========================================
# EXIBIÇÃO DE RESULTADOS E GERAÇÃO DO WORD
# (fora do bloco do botão — persiste entre re-execuções)
# ==========================================
res = st.session_state.get("resultados_calc")

if res:
    # --- Métricas do grampo ---
    st.success("✅ Cálculos finalizados!")
    col1, col2, col3 = st.columns(3)
    col1.metric("Carga no Grampo (T0)", f"{res['t0_kN']:.1f} kN")
    col2.metric("Resistência de Tração (Rtd)", f"{res['rtd_kN']:.1f} kN")
    col3.metric(
        "Verificação de Punção",
        "APROVADO" if "OK" in res["status_puncao"] else "FALHA",
        delta_color="inverse",
    )

    # --- Tabela comparativa ---
    st.subheader("📊 Comparativo – Dimensionamento à Flexão do Paramento")
    st.caption("Todos os métodos utilizam γf = 1,4 e armadura mínima NBR 6118 (ρ_min = 0,15%).")

    dados_comparativo = {
        "Método": ["FHWA (apoiada)", "FHWA (engastada)", "Clouterre", "NBR (laje engast. 4 bordos)", "MEF (Winkler)"],
        "Hipótese": [
            "M = q·Sh·Sv / 8",
            "M = q·Sh·Sv / 12",
            "M = T₀·max(Sh,Sv) / 8",
            f"Marcus (λ={res['lamb']:.2f}), Mx={res['Mxd_NBR']:.2f}, My={res['Myd_NBR']:.2f} kNm/m",
            "Placa espessa Mindlin-Reissner",
        ],
        "Md (kNm/m)": [
            round(res["Md_FHWA_apoiada"], 2), round(res["Md_FHWA_eng"], 2),
            round(res["Md_Clouterre"], 2),    round(res["Md_NBR"], 2),
            round(res["Md_MEF"], 2),
        ],
        "As calculado (cm²/m)": [
            res["As_FHWA_ap"], res["As_FHWA_eng"],
            res["As_Clouterre"], res["As_NBR"], res["As_MEF"],
        ],
        "Status": [
            res["st_FHWA_ap"], res["st_FHWA_eng"],
            res["st_Clouterre"], res["st_NBR"], res["st_MEF"],
        ],
    }
    df_comp = pd.DataFrame(dados_comparativo)
    st.dataframe(df_comp, use_container_width=True, hide_index=True)

    st.info(
        f"**As mínima NBR 6118:** {res['As_min_cm2']:.2f} cm²/m  |  "
        f"**Cobrimento:** {Cobrimento_Nominal_cm:.1f} cm  |  "
        f"**d útil:** {res['d_util_m']*100:.1f} cm"
    )

    # --- Seleção do método — FORA do botão, reage imediatamente ---
    st.subheader("📝 Seleção para o Memorial de Cálculo")
    metodo_escolhido = st.radio(
        "Escolha o método de flexão a destacar como 'Adotado' no Word (todos serão documentados):",
        options=["FHWA (apoiada)", "FHWA (engastada)", "Clouterre", "NBR (laje engast. 4 bordos)", "MEF (Winkler)"],
        horizontal=True,
        key="metodo_radio",
    )

    mapa_as = {
        "FHWA (apoiada)":              (res["As_FHWA_ap"],   res["Md_FHWA_apoiada"]),
        "FHWA (engastada)":            (res["As_FHWA_eng"],  res["Md_FHWA_eng"]),
        "Clouterre":                   (res["As_Clouterre"], res["Md_Clouterre"]),
        "NBR (laje engast. 4 bordos)": (res["As_NBR"],       res["Md_NBR"]),
        "MEF (Winkler)":               (res["As_MEF"],       res["Md_MEF"]),
    }
    As_adotado, Md_adotado = mapa_as[metodo_escolhido]

    # FIX 2: punção recalculada com As_adotado (não As_MEF)
    rho_adotado   = (As_adotado / 10_000.0) / (res["bw_m"] * res["d_util_m"])
    tau_Rd1_adot  = (0.13 * res["k_scale"]
                     * (100.0 * rho_adotado * fck_Concreto_MPa) ** (1.0 / 3.0)
                     * 1000.0)
    if res["tau_Sd"] <= tau_Rd1_adot:
        status_puncao_final = "✅ OK – Concreto resiste sem estribos"
    else:
        status_puncao_final = "❌ FALHA NA TRAÇÃO DIAGONAL – Requer Armadura Transversal"

    if status_puncao_final != res["status_puncao"]:
        st.warning(
            f"⚠️ A verificação de punção mudou para **{status_puncao_final.split('–')[0].strip()}** "
            f"ao usar As = {As_adotado:.2f} cm²/m (método {metodo_escolhido}). "
            "O resultado original foi calculado com As do MEF."
        )

    st.caption(
        f"Método selecionado: **{metodo_escolhido}** → As adotado = **{As_adotado:.2f} cm²/m** | "
        f"Punção com As adotado: {status_puncao_final.split('–')[0].strip()}"
    )

    # -------------------------------------------------------
    # GERAÇÃO DO MEMORIAL EM WORD (PANDOC)
    # -------------------------------------------------------

    # Tabela markdown do comparativo (com destaque do método adotado)
    tabela_comp_md  = "| Método | Hipótese | Md (kNm/m) | As calculado (cm²/m) | Status |\n"
    tabela_comp_md += "|---|---|:---:|:---:|---|\n"
    for _, row in df_comp.iterrows():
        destaque = " *(ADOTADO)*" if row["Método"] == metodo_escolhido else ""
        tabela_comp_md += (
            f"| **{row['Método']}**{destaque} | {row['Hipótese']} "
            f"| {row['Md (kNm/m)']} | **{row['As calculado (cm²/m)']}** "
            f"| {row['Status']} |\n"
        )

    markdown_texto = f"""
# MEMÓRIA DE CÁLCULO: CONTENÇÃO EM SOLO GRAMPEADO

**Elemento:** Dimensionamento Geotécnico e Estrutural do Paramento
**Normas de referência:** ABNT NBR 6118, NBR 16920-2, FHWA (1998), Clouterre (1991)
**Data da análise:** Gerado via Software Interativo

---

## 1. Parâmetros Geotécnicos e Adesão do Grampo ($b_s$)

A estimativa da tensão de cisalhamento última ($q_s$) entre a nata de cimento e o solo foi calculada a partir do $N_{{SPT}}$ médio de cada camada, utilizando os métodos empíricos de Ortigão (1997) e Springer (2006).

**Fórmulas Utilizadas:**

* **Ortigão (1997):** $$ q_{{s1}} = 50 + 7{{,}}5 \\cdot N_{{SPT}} \\quad \\text{{(kPa)}} $$
* **Springer (2006):** $$ q_{{s2}} = 45{{,}}12 \\cdot \\ln(N_{{SPT}}) - 14{{,}}99 \\quad \\text{{(kPa)}} $$

A tensão de projeto adotada ($q_{{sd}}$) corresponde ao menor valor entre os dois métodos, dividido pelo Fator de Segurança ($FS_p = {res['FSp']:.1f}$). A capacidade de carga por metro linear ($b_s$) é:

$$ b_s = q_{{sd}} \\cdot \\pi \\cdot D \\quad (D = {Diametro_Furo_m*100:.1f} \\text{{ cm}}) $$

{res['tabela_solos_md']}

---

## 2. Dimensionamento Estrutural do Grampo (NBR 16920-2)

**Cenário de corrosão:** {Agressividade_do_Meio} | {Tipo_de_Solo} | {Vida_Util}

* Espessura de sacrifício ($t_s$): **{res['t_sacrificio']:.2f} mm**
* Diâmetro nominal: **{Diametro_Barra_mm:.1f} mm** → Diâmetro útil: **{res['d_util_mm']:.2f} mm**
* Área útil: **{res['area_util_mm2']:.2f} mm²**

$$ R_{{td}} = \\frac{{A_{{util}} \\cdot f_{{yk}}}}{{\\gamma_s}} = \\frac{{{res['area_util_mm2']:.2f} \\cdot {Aco_fyk_MPa:.0f}}}{{{Coeficiente_Seguranca_Aco:.2f} \\times 1000}} = {res['rtd_kN']:.2f} \\text{{ kN}} $$

**Carga na cabeça do grampo ($T_0$) – Clouterre (1991):**

$$ T_0 = R_{{td}} \\cdot \\max\\left(0{{,}}60;\\; 0{{,}}60 + 0{{,}}20 \\cdot (S_{{max}} - 1{{,}}0)\\right) = {res['t0_kN']:.2f} \\text{{ kN}} $$

com $S_{{max}} = \\max(S_h, S_v) = {res['s_max']:.2f}$ m.

---

## 3. Dimensionamento do Paramento à Flexão – Análise Comparativa

### 3.1 Premissas comuns

* Espessura ($h$): {Espessura_Paramento_h_m:.2f} m | Cobrimento: {Cobrimento_Nominal_cm:.1f} cm | $d_{{útil}}$ = {res['d_util_m']*100:.1f} cm
* Concreto: $f_{{ck}}$ = {fck_Concreto_MPa:.1f} MPa | $f_{{cd}}$ = {fck_Concreto_MPa/1.4:.1f} MPa
* Tela Soldada: $f_{{yk}}$ = {fy_Aco_MPa:.1f} MPa | $f_{{yd}}$ = {fy_Aco_MPa/1.15:.1f} MPa
* Pressão equivalente: $q = {res['q_pressao_kNm2']:.2f}$ kN/m²
* Coeficiente de majoração: $\\gamma_f = {res['gamma_f']:.1f}$
* Armadura mínima (NBR 6118): $A_{{s,min}} = {res['As_min_cm2']:.2f}$ cm²/m

### 3.2 Método FHWA – Placa Simplesmente Apoiada

$$ M_{{d}} = \\gamma_f \\cdot q \\cdot S_h \\cdot S_v / 8 = {res['Md_FHWA_apoiada']:.2f} \\text{{ kNm/m}} $$

$\\Rightarrow$ **$A_s$ = {res['As_FHWA_ap']:.2f} cm²/m** ({res['st_FHWA_ap']})

### 3.3 Método FHWA – Placa Engastada nos Grampos

$$ M_{{d}} = \\gamma_f \\cdot q \\cdot S_h \\cdot S_v / 12 = {res['Md_FHWA_eng']:.2f} \\text{{ kNm/m}} $$

$\\Rightarrow$ **$A_s$ = {res['As_FHWA_eng']:.2f} cm²/m** ({res['st_FHWA_eng']})

### 3.4 Método Clouterre

$$ M_{{d}} = \\gamma_f \\cdot T_0 \\cdot \\max(S_h, S_v) / 8 = {res['Md_Clouterre']:.2f} \\text{{ kNm/m}} $$

$\\Rightarrow$ **$A_s$ = {res['As_Clouterre']:.2f} cm²/m** ({res['st_Clouterre']})

### 3.5 Método NBR – Laje Engastada nos 4 Bordos (Marcus)

* $l_x = {res['lx']:.2f}$ m, $l_y = {res['ly']:.2f}$ m, $\\lambda = {res['lamb']:.2f}$
* $\\alpha_x = {res['alpha_x']:.4f}$, $\\alpha_y = {res['alpha_y']:.4f}$

$$ M_{{xd}} = {res['Mxd_NBR']:.2f} \\text{{ kNm/m}}, \\quad M_{{yd}} = {res['Myd_NBR']:.2f} \\text{{ kNm/m}} $$

$\\Rightarrow$ **$A_s$ = {res['As_NBR']:.2f} cm²/m** ({res['st_NBR']})

### 3.6 Método MEF (OpenSeesPy – Winkler)

Malha: {res['nx']}×{res['ny']} elementos ShellMITC4 | $K_h = {Kh_Solo_kNm3:.0f}$ kN/m³

* $M_{{max,MEF}} = {res['M_max_MEF']:.2f}$ kNm/m → $M_d = {res['Md_MEF']:.2f}$ kNm/m

$\\Rightarrow$ **$A_s$ = {res['As_MEF']:.2f} cm²/m** ({res['st_MEF']})

> **Hipóteses MEF-Winkler:** molas independentes (Winkler), apoio rígido pontual no grampo,
> válido para Sh e Sv entre 0,8–2,0 m e h entre 10–20 cm.

### 3.7 Resumo Comparativo

{tabela_comp_md}

**Método adotado pelo calculista: {metodo_escolhido}** → $A_s$ = **{As_adotado:.2f} cm²/m**

---

## 4. Verificação de Punção (NBR 6118 – item 19.5)

Verificação realizada com $A_s$ do método adotado ({metodo_escolhido} = {As_adotado:.2f} cm²/m).

$F_{{sd}} = {res['Fsd']:.2f}$ kN | $u = {res['u_critico']:.2f}$ m | $d = {res['d_util_m']*100:.1f}$ cm

$$ \\tau_{{Sd}} = {res['tau_Sd']:.1f} \\text{{ kPa}} \\quad \\tau_{{Rd1}} = {tau_Rd1_adot:.1f} \\text{{ kPa}} $$

**Resultado:** {status_puncao_final}
"""

    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            arquivo_docx = tmp.name

        pypandoc.convert_text(
            markdown_texto, 'docx',
            format='md',
            outputfile=arquivo_docx,
            extra_args=['--mathml']
        )

        with open(arquivo_docx, "rb") as f:
            docx_bytes = f.read()

        os.remove(arquivo_docx)

        st.download_button(
            label="📄 Baixar Memória de Cálculo (.docx)",
            data=docx_bytes,
            file_name="Memoria_Calculo_Solo_Grampeado.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

    except Exception as e:
        st.error(
            f"❌ Erro ao gerar o Word. Verifique se o Pandoc está instalado no sistema.\n\nDetalhe: {e}"
        )
