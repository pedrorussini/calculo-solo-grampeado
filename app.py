import streamlit as st
import pandas as pd
import math
import openseespy.opensees as ops
import pypandoc
import os
import tempfile

# ==========================================
# SESSION STATE
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
# BARRA LATERAL
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

    st.header("3. Grampo e Perfuração")
    Comprimento_Grampo_m      = st.number_input("Comprimento do Grampo L (m)", value=8.0, step=0.5)
    Inclinacao_Grampo_graus   = st.number_input("Inclinação do Grampo α (°)", value=15.0, step=1.0)
    Diametro_Furo_m           = st.number_input("Diâmetro do Furo (m)", value=0.10, step=0.01)
    Diametro_Barra_mm         = st.number_input("Diâmetro da Barra (mm)", value=25.0, step=1.0)
    Aco_fyk_MPa               = st.number_input("fyk da Barra (MPa)", value=500.0, step=10.0)
    Coeficiente_Seguranca_Aco = st.number_input("Coef. Segurança Aço (γs)", value=1.15, step=0.05)

    st.header("4. Fileiras de Grampos")
    Prof_Primeira_Fileira_m = st.number_input(
        "Prof. da 1ª Fileira (m)", value=0.75, step=0.25,
        help="Profundidade do ponto de instalação desde a superfície"
    )
    Numero_Fileiras = st.number_input("Número de Fileiras", value=4, step=1, min_value=1)

    st.header("5. Corrosão (NBR 16920-2)")
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
# TELA PRINCIPAL — ESTRATIGRAFIA
# ==========================================
st.subheader("Camadas de Solo (Estratigrafia, NSPT e Kh)")
st.write(
    "Informe as camadas do maciço. O **Kh** de cada camada é usado nas molas do MEF-Winkler. "
    "O app identifica automaticamente qual camada cada fileira de grampos perfura."
)

df_padrao = pd.DataFrame([
    {"Classe NBR": "Argilas e siltes argilosos", "Estado NBR": "Rija(o)",
     "Espessura (m)": 4.0, "NSPT Médio": 15, "Kh (kN/m³)": 20000.0},
    {"Classe NBR": "Areias e siltes arenosos",   "Estado NBR": "Compacta(o)",
     "Espessura (m)": 6.0, "NSPT Médio": 20, "Kh (kN/m³)": 40000.0},
])
df_solos = st.data_editor(df_padrao, num_rows="dynamic", use_container_width=True)

# ==========================================
# TABELA DE FILEIRAS (gerada automaticamente, editável)
# ==========================================
st.subheader("Fileiras de Grampos")
st.caption(
    f"Profundidades geradas automaticamente: 1ª fileira a {Prof_Primeira_Fileira_m:.2f} m, "
    f"Sv = {Espacamento_Sv_m:.2f} m. Edite se necessário."
)
prof_auto = [
    round(Prof_Primeira_Fileira_m + k * Espacamento_Sv_m, 3)
    for k in range(int(Numero_Fileiras))
]
df_fil_padrao = pd.DataFrame({
    "Fileira":               [f"F{k+1}" for k in range(int(Numero_Fileiras))],
    "Prof. instalação (m)":  prof_auto,
})
df_fileiras = st.data_editor(df_fil_padrao, num_rows="fixed",
                              use_container_width=True, disabled=["Fileira"])

# ==========================================
# PAINEL DE AVISOS CONTEXTUAIS
# ==========================================
st.markdown("---")

FAIXA_Sh    = (0.8, 2.0)
FAIXA_Sv    = (0.8, 2.0)
FAIXA_h     = (0.10, 0.20)
FAIXA_fck   = (20.0, 35.0)
FAIXA_Kh    = (5000, 80000)

avisos_info   = []
avisos_alerta = []

if not (FAIXA_h[0] <= Espessura_Paramento_h_m <= FAIXA_h[1]):
    avisos_info.append(
        f"**Espessura do paramento ({Espessura_Paramento_h_m*100:.0f} cm)** fora da faixa usual "
        f"({FAIXA_h[0]*100:.0f}–{FAIXA_h[1]*100:.0f} cm). Confronte o MEF com software dedicado."
    )
if not (FAIXA_Sh[0] <= Espacamento_Sh_m <= FAIXA_Sh[1]):
    avisos_info.append(
        f"**Sh = {Espacamento_Sh_m:.2f} m** fora da faixa validada ({FAIXA_Sh[0]:.1f}–{FAIXA_Sh[1]:.1f} m)."
    )
if not (FAIXA_Sv[0] <= Espacamento_Sv_m <= FAIXA_Sv[1]):
    avisos_info.append(
        f"**Sv = {Espacamento_Sv_m:.2f} m** fora da faixa validada ({FAIXA_Sv[0]:.1f}–{FAIXA_Sv[1]:.1f} m)."
    )
razao_sv = Espacamento_Sh_m / Espacamento_Sv_m if Espacamento_Sv_m > 0 else 1.0
if max(razao_sv, 1/razao_sv) > 2.0:
    avisos_info.append(
        f"**Razão Sh/Sv = {razao_sv:.2f}** — painel muito alongado. Marcus perde precisão para λ > 2,0."
    )
if not (FAIXA_fck[0] <= fck_Concreto_MPa <= FAIXA_fck[1]):
    avisos_info.append(
        f"**fck = {fck_Concreto_MPa:.0f} MPa** fora da faixa típica de concreto projetado "
        f"({FAIXA_fck[0]:.0f}–{FAIXA_fck[1]:.0f} MPa)."
    )
if not df_solos.empty and "Kh (kN/m³)" in df_solos.columns:
    for kh in df_solos["Kh (kN/m³)"].dropna():
        if not (FAIXA_Kh[0] <= kh <= FAIXA_Kh[1]):
            avisos_info.append(
                f"**Kh = {kh:,.0f} kN/m³** fora da faixa usual "
                f"({FAIXA_Kh[0]:,}–{FAIXA_Kh[1]:,} kN/m³)."
            )
            break
cobrimento_m = Cobrimento_Nominal_cm / 100.0
if cobrimento_m / Espessura_Paramento_h_m > 0.25:
    avisos_alerta.append(
        f"**Cobrimento ({Cobrimento_Nominal_cm:.1f} cm) = "
        f"{cobrimento_m/Espessura_Paramento_h_m*100:.0f}% da espessura.** "
        "d útil muito reduzido — verifique NBR 14931."
    )
try:
    sin_a_prev = math.sin(math.radians(float(Inclinacao_Grampo_graus)))
    if sin_a_prev > 0 and not df_solos.empty and not df_fileiras.empty:
        prof_max = df_fileiras["Prof. instalação (m)"].max()
        proj_v   = Comprimento_Grampo_m * sin_a_prev
        total_sp = df_solos["Espessura (m)"].sum()
        if prof_max + proj_v > total_sp:
            avisos_alerta.append(
                f"**Grampo pode ultrapassar o perfil informado.** "
                f"Última fileira ({prof_max:.2f} m) + projeção vertical ({proj_v:.2f} m) "
                f"> espessura total do perfil ({total_sp:.2f} m)."
            )
except Exception:
    pass

avisos_mef = (
    "**Hipóteses do modelo MEF-Winkler:** "
    "_(i)_ Molas independentes de Winkler — sem transferência lateral de carga entre pontos adjacentes. "
    "_(ii)_ Grampo simulado como apoio rígido pontual no nó central. "
    "_(iii)_ Kh usado no MEF = menor Kh das camadas perfuradas pela fileira governante "
    "(critério conservador: menor rigidez → maior deflexão → maior momento). "
    f"_(iv)_ Faixas de validade: Sh e Sv entre {FAIXA_Sh[0]:.1f}–{FAIXA_Sh[1]:.1f} m, "
    f"h entre {FAIXA_h[0]*100:.0f}–{FAIXA_h[1]*100:.0f} cm."
)

with st.expander("ℹ️ Avisos e hipóteses do modelo", expanded=bool(avisos_alerta or avisos_info)):
    st.info(avisos_mef)
    for a in avisos_alerta:
        st.error("🔴 " + a)
    for a in avisos_info:
        st.warning("⚠️ " + a)
    if not avisos_alerta and not avisos_info:
        st.success("✅ Parâmetros dentro das faixas validadas (desvio MEF esperado < 15%).")

# ==========================================
# MOTOR DE CÁLCULO
# ==========================================
if st.button("🚀 Processar Cálculo e Gerar Memorial (Word)", type="primary", use_container_width=True):
    with st.spinner("Calculando resistência por fileira e executando MEF..."):

        # ----------------------------------------------------------
        # VALIDAÇÕES
        # ----------------------------------------------------------
        erros = []
        if Cobrimento_Nominal_cm / 100.0 >= Espessura_Paramento_h_m:
            erros.append("Cobrimento nominal deve ser menor que a espessura do paramento.")
        if Diametro_Barra_mm / 1000.0 >= Diametro_Furo_m:
            erros.append("Diâmetro da barra deve ser menor que o diâmetro do furo.")
        if df_solos["NSPT Médio"].isnull().any() or (df_solos["NSPT Médio"] < 0).any():
            erros.append("Todos os valores de NSPT devem ser preenchidos e não-negativos.")
        if df_solos["Kh (kN/m³)"].isnull().any() or (df_solos["Kh (kN/m³)"] <= 0).any():
            erros.append("Todos os valores de Kh devem ser preenchidos e positivos.")
        if df_fileiras["Prof. instalação (m)"].isnull().any():
            erros.append("Todas as fileiras devem ter profundidade de instalação informada.")
        if not (0 < Inclinacao_Grampo_graus < 90):
            erros.append("Inclinação do grampo deve estar entre 0° e 90°.")
        if erros:
            for e in erros:
                st.error("⚠️ " + e)
            st.stop()

        # ----------------------------------------------------------
        # 1. MÓDULO GEOTÉCNICO — bs por camada
        # ----------------------------------------------------------
        FSp   = 2.0
        sin_a = math.sin(math.radians(Inclinacao_Grampo_graus))

        camadas = []
        prof_ac = 0.0
        for _, row in df_solos.iterrows():
            nspt     = float(row["NSPT Médio"])
            esp      = float(row["Espessura (m)"])
            kh_cam   = float(row["Kh (kN/m³)"])
            prof_ini = prof_ac
            prof_fim = prof_ac + esp
            prof_ac  = prof_fim

            qs1 = qsd1 = qs2 = qsd2 = qsd = bs = 0.0
            if nspt > 0:
                qs1  = 50 + 7.5 * nspt
                qsd1 = qs1 / FSp
                qs2  = max((45.12 * math.log(nspt)) - 14.99, 0.0) if nspt > 1 else 0.0
                qsd2 = qs2 / FSp
                qsd  = min(qsd1, qsd2)
                bs   = qsd * math.pi * Diametro_Furo_m
            else:
                st.warning(f"⚠️ Camada {prof_ini:.1f}–{prof_fim:.1f} m: NSPT = 0 → bs = 0.")

            camadas.append({
                "classe": row["Classe NBR"], "estado": row["Estado NBR"],
                "nspt": nspt, "esp": esp,
                "prof_ini": prof_ini, "prof_fim": prof_fim,
                "qsd1": round(qsd1, 2), "qsd2": round(qsd2, 2),
                "qsd": round(qsd, 2), "bs": round(bs, 2),
                "kh": kh_cam,
            })

        tabela_solos_md  = "| Trecho (m) | Solo (NBR) | NSPT | qsd Ortigão | qsd Springer | qsd Adotado | bs (kN/m) | Kh (kN/m³) |\n"
        tabela_solos_md += "|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|\n"
        for c in camadas:
            tabela_solos_md += (
                f"| {c['prof_ini']:.1f}–{c['prof_fim']:.1f} | {c['classe']} ({c['estado']}) "
                f"| {c['nspt']:.0f} | {c['qsd1']} | {c['qsd2']} "
                f"| **{c['qsd']}** | **{c['bs']}** | {c['kh']:,.0f} |\n"
            )

        # ----------------------------------------------------------
        # 2. MÓDULO DO GRAMPO — R_td e T0 por fileira
        # ----------------------------------------------------------
        t_sacrificio  = tabela_corrosao[Agressividade_do_Meio][Tipo_de_Solo][Vida_Util]
        diam_util_mm  = max(Diametro_Barra_mm - 2 * t_sacrificio, 0.0)
        area_util_mm2 = (math.pi * diam_util_mm ** 2) / 4.0
        Rtd_barra_kN  = (area_util_mm2 * Aco_fyk_MPa) / (Coeficiente_Seguranca_Aco * 1000.0)

        s_max           = max(Espacamento_Sh_m, Espacamento_Sv_m)
        fator_clouterre = max(0.60 + 0.20 * (s_max - 1.0), 0.60)

        def calcular_fileira(z_inst: float) -> dict:
            """
            Calcula R_td e T0 para um grampo instalado na profundidade z_inst.
            O grampo desce com inclinação α ao longo do comprimento L.
            Profundidade vertical final: z_inst + L * sin(α).
            Para cada camada intersectada:
                delta_z = sobreposição vertical entre [z_inst, z_fim] e [prof_ini, prof_fim]
                L_i     = delta_z / sin(α)   (comprimento real no eixo do grampo)
                R_i     = bs_i * L_i          (bs já contém FS_p)
            R_td é limitado pelo menor entre R_arr (arrancamento) e Rtd_barra (ruptura da barra).
            """
            z_fim   = z_inst + Comprimento_Grampo_m * sin_a
            trechos = []
            R_arr   = 0.0

            for c in camadas:
                z0 = max(z_inst, c["prof_ini"])
                z1 = min(z_fim,  c["prof_fim"])
                if z1 <= z0:
                    continue
                L_i   = (z1 - z0) / sin_a
                R_i   = c["bs"] * L_i
                R_arr += R_i
                trechos.append({
                    "camada": f"{c['prof_ini']:.1f}–{c['prof_fim']:.1f} m",
                    "classe": c["classe"],
                    "bs":     c["bs"],
                    "L_i":    round(L_i, 3),
                    "R_i":    round(R_i, 2),
                })

            Rtd_fil = min(R_arr, Rtd_barra_kN)
            T0_fil  = Rtd_fil * fator_clouterre

            return {
                "z_inst":  z_inst,
                "z_fim":   round(z_fim, 3),
                "trechos": trechos,
                "R_arr":   round(R_arr, 2),
                "Rtd":     round(Rtd_fil, 2),
                "T0":      round(T0_fil, 2),
                "governa_barra": R_arr >= Rtd_barra_kN,
            }

        resultados_fileiras = [
            calcular_fileira(float(r["Prof. instalação (m)"]))
            for _, r in df_fileiras.iterrows()
        ]

        # Fileira governante = menor T0
        idx_gov = min(range(len(resultados_fileiras)),
                      key=lambda i: resultados_fileiras[i]["T0"])
        fil_gov = resultados_fileiras[idx_gov]
        t0_kN   = fil_gov["T0"]
        rtd_kN  = fil_gov["Rtd"]

        tabela_fileiras_md  = "| Fileira | Prof. inst. (m) | Prof. fim (m) | R_arr (kN) | R_td (kN) | T0 (kN) | Limitada por |\n"
        tabela_fileiras_md += "|:---:|:---:|:---:|:---:|:---:|:---:|---|\n"
        for k, f in enumerate(resultados_fileiras):
            gov  = " **← GOVERNANTE**" if k == idx_gov else ""
            lim  = "Barra" if f["governa_barra"] else "Arrancamento"
            tabela_fileiras_md += (
                f"| F{k+1} | {f['z_inst']:.2f} | {f['z_fim']:.2f} "
                f"| {f['R_arr']} | {f['Rtd']} | **{f['T0']}**{gov} | {lim} |\n"
            )

        # Tabela de trechos da fileira governante
        tabela_trechos_md  = "| Camada | Solo | bs (kN/m) | L_i (m) | R_i (kN) |\n"
        tabela_trechos_md += "|:---:|---|:---:|:---:|:---:|\n"
        for t in fil_gov["trechos"]:
            tabela_trechos_md += (
                f"| {t['camada']} | {t['classe']} | {t['bs']} | {t['L_i']} | {t['R_i']} |\n"
            )
        L_total_gov = sum(t["L_i"] for t in fil_gov["trechos"])
        tabela_trechos_md += f"| **Total** | | | **{L_total_gov:.3f}** | **{fil_gov['R_arr']}** |\n"

        # Kh conservador para MEF = menor Kh das camadas da fileira governante
        kh_gov = [
            c["kh"] for c in camadas
            if min(fil_gov["z_fim"], c["prof_fim"]) > max(fil_gov["z_inst"], c["prof_ini"])
        ]
        Kh_MEF = min(kh_gov) if kh_gov else camadas[0]["kh"]

        # ----------------------------------------------------------
        # 3. MÓDULO DO PARAMENTO — QUATRO MÉTODOS DE FLEXÃO
        # ----------------------------------------------------------
        q_pressao_kNm2 = t0_kN / (Espacamento_Sh_m * Espacamento_Sv_m)
        d_util_m       = Espessura_Paramento_h_m - (Cobrimento_Nominal_cm / 100.0)
        bw_m           = 1.0
        fcd_kN_m2      = (fck_Concreto_MPa / 1.4) * 1000.0
        fyd_kN_m2      = (fy_Aco_MPa * 1000.0) / 1.15
        gamma_f        = 1.4
        As_min_cm2     = 0.0015 * bw_m * Espessura_Paramento_h_m * 10_000.0

        def dim_as(Md):
            Kmd = Md / (bw_m * d_util_m**2 * fcd_kN_m2)
            if Kmd <= 0.259:
                kx = (1 - math.sqrt(1 - 2.36*Kmd)) / 1.18
                z  = d_util_m * (1 - 0.4*kx)
                As = (Md / (z * fyd_kN_m2)) * 10_000.0
                st = "OK"
            else:
                As, st = 999.0, "ERRO – seção insuficiente (Kmd > 0.259)"
            return round(max(As, As_min_cm2), 2), st

        Md_FHWA_ap  = gamma_f * q_pressao_kNm2 * Espacamento_Sh_m * Espacamento_Sv_m / 8.0
        As_FHWA_ap,  st_FHWA_ap  = dim_as(Md_FHWA_ap)

        Md_FHWA_eng = gamma_f * q_pressao_kNm2 * Espacamento_Sh_m * Espacamento_Sv_m / 12.0
        As_FHWA_eng, st_FHWA_eng = dim_as(Md_FHWA_eng)

        Md_Clout    = gamma_f * t0_kN * max(Espacamento_Sh_m, Espacamento_Sv_m) / 8.0
        As_Clout,    st_Clout    = dim_as(Md_Clout)

        lx   = min(Espacamento_Sh_m, Espacamento_Sv_m)
        ly   = max(Espacamento_Sh_m, Espacamento_Sv_m)
        lamb = ly / lx
        lambdas  = [1.0,  1.1,   1.2,   1.3,   1.4,   1.5,   1.75,  2.0]
        alphas_x = [0.0513,0.0581,0.0639,0.0687,0.0726,0.0756,0.0812,0.0829]
        alphas_y = [0.0513,0.0430,0.0365,0.0312,0.0271,0.0238,0.0183,0.0158]

        def interp(xv, xs, ys):
            if xv <= xs[0]:  return ys[0]
            if xv >= xs[-1]: return ys[-1]
            for i in range(len(xs)-1):
                if xs[i] <= xv <= xs[i+1]:
                    t = (xv-xs[i])/(xs[i+1]-xs[i])
                    return ys[i] + t*(ys[i+1]-ys[i])
            return ys[-1]

        ax      = interp(lamb, lambdas, alphas_x)
        ay      = interp(lamb, lambdas, alphas_y)
        Mxd_NBR = gamma_f * ax * q_pressao_kNm2 * lx**2
        Myd_NBR = gamma_f * ay * q_pressao_kNm2 * lx**2
        Md_NBR  = max(Mxd_NBR, Myd_NBR)
        As_NBR,  st_NBR  = dim_as(Md_NBR)

        # MEF Winkler com Kh conservador
        ops.wipe()
        ops.model('basic', '-ndm', 3, '-ndf', 6)
        nx, ny = 15, 15
        dx = Espacamento_Sh_m / nx
        dy = Espacamento_Sv_m / ny
        E_c = 4760.0 * math.sqrt(fck_Concreto_MPa) * 1000.0

        node_tag = 1
        for j in range(ny+1):
            for i in range(nx+1):
                ops.node(node_tag, i*dx - Espacamento_Sh_m/2.0,
                         j*dy - Espacamento_Sv_m/2.0, 0.0)
                ops.fix(node_tag, 0, 0, 0, 0, 0, 1)
                node_tag += 1
        n_nos = node_tag - 1

        mat_base = 50000
        for n in range(1, n_nos+1):
            c = ops.nodeCoord(n)
            ops.node(n+mat_base, c[0], c[1], -0.001)
            ops.fix(n+mat_base, 1, 1, 1, 1, 1, 1)
            ops.uniaxialMaterial('Elastic', n, Kh_MEF*dx*dy)
            ops.element('zeroLength', n+mat_base, n, n+mat_base, '-mat', n, '-dir', 3)

        ops.section('ElasticMembranePlateSection', 1, E_c, 0.2, Espessura_Paramento_h_m, 0.0)

        ele_tag = 1
        for j in range(ny):
            for i in range(nx):
                n1 = j*(nx+1)+i+1
                ops.element('ShellMITC4', ele_tag, n1, n1+1, n1+1+(nx+1), n1+(nx+1), 1)
                ele_tag += 1
        n_eles = ele_tag - 1

        center_node = int((ny//2)*(nx+1)+(nx//2)+1)
        ops.fix(center_node, 1, 1, 1, 0, 0, 0)

        ops.timeSeries('Linear', 1)
        ops.pattern('Plain', 1, 1)
        Fz_int = -q_pressao_kNm2 * dx * dy
        for j in range(ny+1):
            for i in range(nx+1):
                nid = j*(nx+1)+i+1
                fx  = 0.5 if (i == 0 or i == nx) else 1.0
                fy  = 0.5 if (j == 0 or j == ny) else 1.0
                ops.load(nid, 0.0, 0.0, Fz_int*fx*fy, 0.0, 0.0, 0.0)

        ops.system('UmfPack');  ops.numberer('RCM');   ops.constraints('Plain')
        ops.integrator('LoadControl', 1.0);  ops.algorithm('Linear')
        ops.analysis('Static');  ops.analyze(1)

        M_max_MEF = 0.0
        for i in range(1, n_eles+1):
            s = ops.eleResponse(i, 'stresses')
            if s and len(s) >= 32:
                for pt in range(4):
                    M_max_MEF = max(M_max_MEF, abs(s[pt*8+3]), abs(s[pt*8+4]))
        if M_max_MEF == 0.0:
            st.warning("⚠️ MEF não retornou momentos — usando fallback q·L²/10.")
            M_max_MEF = q_pressao_kNm2 * max(Espacamento_Sh_m, Espacamento_Sv_m)**2 / 10.0

        Md_MEF = M_max_MEF * gamma_f
        As_MEF, st_MEF = dim_as(Md_MEF)

        # ----------------------------------------------------------
        # 4. PUNÇÃO (NBR 6118)
        # ----------------------------------------------------------
        Fsd       = t0_kN * gamma_f
        u_critico = 4*Largura_Placa_bp_m + 2*math.pi*(2*d_util_m)
        tau_Sd    = Fsd / (u_critico * d_util_m)
        k_scale   = min(1 + math.sqrt(20.0/(d_util_m*100.0)), 2.0)

        # ----------------------------------------------------------
        # 5. SALVAR SESSION STATE
        # ----------------------------------------------------------
        st.session_state["resultados_calc"] = {
            "t0_kN": t0_kN, "rtd_kN": rtd_kN,
            "fator_clouterre": fator_clouterre, "s_max": s_max,
            "t_sacrificio": t_sacrificio, "diam_util_mm": diam_util_mm,
            "area_util_mm2": area_util_mm2, "Rtd_barra_kN": Rtd_barra_kN,
            "resultados_fileiras": resultados_fileiras,
            "idx_gov": idx_gov, "fil_gov": fil_gov,
            "tabela_fileiras_md": tabela_fileiras_md,
            "tabela_trechos_md": tabela_trechos_md,
            "L_total_gov": L_total_gov,
            "Kh_MEF": Kh_MEF,
            "M_max_MEF": M_max_MEF, "Md_MEF": Md_MEF,
            "As_MEF": As_MEF, "st_MEF": st_MEF,
            "nx": nx, "ny": ny,
            "Md_FHWA_ap": Md_FHWA_ap, "As_FHWA_ap": As_FHWA_ap, "st_FHWA_ap": st_FHWA_ap,
            "Md_FHWA_eng": Md_FHWA_eng, "As_FHWA_eng": As_FHWA_eng, "st_FHWA_eng": st_FHWA_eng,
            "Md_Clout": Md_Clout, "As_Clout": As_Clout, "st_Clout": st_Clout,
            "Md_NBR": Md_NBR, "As_NBR": As_NBR, "st_NBR": st_NBR,
            "Mxd_NBR": Mxd_NBR, "Myd_NBR": Myd_NBR,
            "lx": lx, "ly": ly, "lamb": lamb, "ax": ax, "ay": ay,
            "Fsd": Fsd, "u_critico": u_critico, "tau_Sd": tau_Sd, "k_scale": k_scale,
            "q_pressao_kNm2": q_pressao_kNm2, "d_util_m": d_util_m,
            "bw_m": bw_m, "gamma_f": gamma_f, "FSp": FSp,
            "As_min_cm2": As_min_cm2, "tabela_solos_md": tabela_solos_md,
        }
        st.success("✅ Cálculos finalizados!")

# ==========================================
# EXIBIÇÃO E GERAÇÃO DO WORD
# ==========================================
res = st.session_state.get("resultados_calc")

if res:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("T0 governante", f"{res['t0_kN']:.1f} kN",
                help=f"Fileira F{res['idx_gov']+1} — menor T0 do conjunto")
    col2.metric("R_td fileira gov.", f"{res['rtd_kN']:.1f} kN")
    col3.metric("Kh MEF (conservador)", f"{res['Kh_MEF']:,.0f} kN/m³",
                help="Menor Kh das camadas da fileira governante")
    col4.metric("q no paramento", f"{res['q_pressao_kNm2']:.2f} kN/m²")

    # Tabela de fileiras
    st.subheader("📋 Resistência por Fileira de Grampos")
    dados_fil = {
        "Fileira":         [f"F{k+1}" + (" ★" if k == res["idx_gov"] else "")
                            for k in range(len(res["resultados_fileiras"]))],
        "Prof. inst. (m)": [f["z_inst"] for f in res["resultados_fileiras"]],
        "Prof. fim (m)":   [f["z_fim"]  for f in res["resultados_fileiras"]],
        "R_arr (kN)":      [f["R_arr"]  for f in res["resultados_fileiras"]],
        "R_td (kN)":       [f["Rtd"]    for f in res["resultados_fileiras"]],
        "T0 (kN)":         [f["T0"]     for f in res["resultados_fileiras"]],
        "Limitada por":    ["Barra" if f["governa_barra"] else "Arrancamento"
                            for f in res["resultados_fileiras"]],
    }
    st.dataframe(pd.DataFrame(dados_fil), use_container_width=True, hide_index=True)
    st.caption(f"★ Fileira governante — dimensiona o paramento. "
               f"Kh conservador para MEF = {res['Kh_MEF']:,.0f} kN/m³.")

    # Comparativo de flexão
    st.subheader("📊 Comparativo – Dimensionamento à Flexão do Paramento")
    st.caption(f"T0 governante = {res['t0_kN']:.1f} kN | γf = 1,4 | As_min = {res['As_min_cm2']:.2f} cm²/m")

    dados_comp = {
        "Método": ["FHWA (apoiada)", "FHWA (engastada)", "Clouterre",
                   "NBR (Marcus 4 bordos)", "MEF (Winkler)"],
        "Hipótese": [
            "M = q·Sh·Sv / 8",
            "M = q·Sh·Sv / 12",
            "M = T₀·max(Sh,Sv) / 8",
            f"Marcus λ={res['lamb']:.2f}, Mx={res['Mxd_NBR']:.2f}, My={res['Myd_NBR']:.2f} kNm/m",
            f"Mindlin-Reissner, Kh={res['Kh_MEF']:,.0f} kN/m³",
        ],
        "Md (kNm/m)": [round(res["Md_FHWA_ap"],2), round(res["Md_FHWA_eng"],2),
                       round(res["Md_Clout"],2),    round(res["Md_NBR"],2),
                       round(res["Md_MEF"],2)],
        "As (cm²/m)": [res["As_FHWA_ap"], res["As_FHWA_eng"],
                       res["As_Clout"],    res["As_NBR"], res["As_MEF"]],
        "Status":     [res["st_FHWA_ap"], res["st_FHWA_eng"],
                       res["st_Clout"],    res["st_NBR"],  res["st_MEF"]],
    }
    df_comp = pd.DataFrame(dados_comp)
    st.dataframe(df_comp, use_container_width=True, hide_index=True)
    st.info(f"**d útil:** {res['d_util_m']*100:.1f} cm  |  "
            f"**Cobrimento:** {Cobrimento_Nominal_cm:.1f} cm  |  "
            f"**As_min:** {res['As_min_cm2']:.2f} cm²/m")

    # Seleção do método
    st.subheader("📝 Seleção para o Memorial")
    metodo_escolhido = st.radio(
        "Método de flexão a destacar como 'Adotado' no Word:",
        options=["FHWA (apoiada)", "FHWA (engastada)", "Clouterre",
                 "NBR (Marcus 4 bordos)", "MEF (Winkler)"],
        horizontal=True,
        key="metodo_radio",
    )
    mapa = {
        "FHWA (apoiada)":        (res["As_FHWA_ap"],  res["Md_FHWA_ap"]),
        "FHWA (engastada)":      (res["As_FHWA_eng"], res["Md_FHWA_eng"]),
        "Clouterre":             (res["As_Clout"],     res["Md_Clout"]),
        "NBR (Marcus 4 bordos)": (res["As_NBR"],       res["Md_NBR"]),
        "MEF (Winkler)":         (res["As_MEF"],       res["Md_MEF"]),
    }
    As_adotado, Md_adotado = mapa[metodo_escolhido]

    rho_adot     = (As_adotado / 10_000.0) / (res["bw_m"] * res["d_util_m"])
    tau_Rd1_adot = (0.13 * res["k_scale"]
                    * (100.0 * rho_adot * fck_Concreto_MPa)**(1.0/3.0) * 1000.0)
    status_puncao = ("✅ OK – Concreto resiste sem estribos"
                     if res["tau_Sd"] <= tau_Rd1_adot
                     else "❌ FALHA NA TRAÇÃO DIAGONAL – Requer Armadura Transversal")

    st.caption(f"**{metodo_escolhido}** → As = **{As_adotado:.2f} cm²/m** | "
               f"Punção: {status_puncao.split('–')[0].strip()}")

    # ----------------------------------------------------------
    # GERAÇÃO DO WORD
    # ----------------------------------------------------------
    tabela_comp_md  = "| Método | Hipótese | Md (kNm/m) | As (cm²/m) | Status |\n"
    tabela_comp_md += "|---|---|:---:|:---:|---|\n"
    for _, row in df_comp.iterrows():
        dest = " *(ADOTADO)*" if row["Método"] == metodo_escolhido else ""
        tabela_comp_md += (
            f"| **{row['Método']}**{dest} | {row['Hipótese']} "
            f"| {row['Md (kNm/m)']} | **{row['As (cm²/m)']}** | {row['Status']} |\n"
        )

    fil = res["fil_gov"]
    markdown_texto = f"""
# MEMÓRIA DE CÁLCULO: CONTENÇÃO EM SOLO GRAMPEADO

**Normas:** ABNT NBR 6118, NBR 16920-2, FHWA (1998), Clouterre (1991)
**Gerado via:** Software Interativo

---

## 1. Perfil Estratigráfico e Adesão do Grampo

Métodos de Ortigão (1997) e Springer (2006) | $FS_p = {res['FSp']:.1f}$ | $D_{{furo}} = {Diametro_Furo_m*100:.1f}$ cm

$$ q_{{s1}} = 50 + 7{{,}}5 \\cdot N_{{SPT}} \\qquad q_{{s2}} = 45{{,}}12 \\cdot \\ln(N_{{SPT}}) - 14{{,}}99 \\quad \\text{{(kPa)}} $$

{res['tabela_solos_md']}

---

## 2. Resistência por Fileira de Grampos

**Grampo:** $L = {Comprimento_Grampo_m:.2f}$ m | $\\alpha = {Inclinacao_Grampo_graus:.1f}°$ | $\\sin(\\alpha) = {sin_a:.4f}$

**Corrosão:** {Agressividade_do_Meio} | {Tipo_de_Solo} | {Vida_Util}
$t_s = {res['t_sacrificio']:.2f}$ mm | $d_{{util}} = {res['diam_util_mm']:.2f}$ mm | $A_{{util}} = {res['area_util_mm2']:.2f}$ mm² | $R_{{td,barra}} = {res['Rtd_barra_kN']:.2f}$ kN

Para cada fileira: $L_i = \\Delta z_i / \\sin(\\alpha)$ e $R_i = b_{{s,i}} \\cdot L_i$

{res['tabela_fileiras_md']}

### Detalhamento da fileira governante: F{res['idx_gov']+1} (T0 = {res['t0_kN']:.2f} kN)

Instalada a {fil['z_inst']:.2f} m | Extremidade a {fil['z_fim']:.2f} m

{res['tabela_trechos_md']}

$R_{{td}} = \\min(R_{{arr}};\\; R_{{td,barra}}) = \\min({fil['R_arr']};\\; {res['Rtd_barra_kN']:.2f}) = {res['rtd_kN']:.2f}$ kN

$T_0 = {res['rtd_kN']:.2f} \\cdot {res['fator_clouterre']:.3f} = {res['t0_kN']:.2f}$ kN $\\quad (S_{{max}} = {res['s_max']:.2f}$ m$)$

---

## 3. Dimensionamento do Paramento à Flexão

$q = T_0 / (S_h \\cdot S_v) = {res['t0_kN']:.2f} / ({Espacamento_Sh_m:.2f} \\times {Espacamento_Sv_m:.2f}) = {res['q_pressao_kNm2']:.2f}$ kN/m²

$h = {Espessura_Paramento_h_m:.2f}$ m | $d = {res['d_util_m']*100:.1f}$ cm | $f_{{ck}} = {fck_Concreto_MPa:.1f}$ MPa | $f_{{yk}} = {fy_Aco_MPa:.1f}$ MPa | $\\gamma_f = {res['gamma_f']:.1f}$

**MEF-Winkler:** Kh conservador = {res['Kh_MEF']:,.0f} kN/m³ (menor Kh das camadas da fileira governante) | Malha {res['nx']}×{res['ny']} ShellMITC4

{tabela_comp_md}

**Método adotado: {metodo_escolhido}** $\\Rightarrow$ $A_s = $ **{As_adotado:.2f} cm²/m**

---

## 4. Verificação de Punção (NBR 6118 – item 19.5)

Verificação com $A_s$ do método adotado ({As_adotado:.2f} cm²/m):

$F_{{sd}} = {res['Fsd']:.2f}$ kN | $u = {res['u_critico']:.2f}$ m | $d = {res['d_util_m']*100:.1f}$ cm

$$ \\tau_{{Sd}} = {res['tau_Sd']:.1f} \\text{{ kPa}} \\qquad \\tau_{{Rd1}} = {tau_Rd1_adot:.1f} \\text{{ kPa}} $$

**Resultado:** {status_puncao}
"""

    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            arquivo_docx = tmp.name
        pypandoc.convert_text(markdown_texto, 'docx', format='md',
                              outputfile=arquivo_docx, extra_args=['--mathml'])
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
        st.error(f"❌ Erro ao gerar o Word. Pandoc instalado? Detalhe: {e}")
