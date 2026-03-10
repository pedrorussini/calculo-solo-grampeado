import streamlit as st
import pandas as pd
import math
import openseespy.opensees as ops
import pypandoc
import os

# ==========================================
# CONFIGURAÇÃO DA PÁGINA
# ==========================================
st.set_page_config(page_title="Solo Grampeado - TIC Trens", page_icon="🏗️", layout="wide")
st.title("🏗️ Memorial de Cálculo: Contenção em Solo Grampeado")
st.markdown("---")

# ==========================================
# BARRA LATERAL (INPUTS DO USUÁRIO)
# ==========================================
with st.sidebar:
    st.header("1. Geometria e Paramento")
    Espessura_Paramento_h_m = st.number_input("Espessura do Paramento (m)", value=0.15, step=0.01)
    Largura_Placa_bp_m = st.number_input("Largura da Placa (m)", value=0.30, step=0.05)
    Espacamento_Sh_m = st.number_input("Espaçamento Sh (m)", value=1.50, step=0.10)
    Espacamento_Sv_m = st.number_input("Espaçamento Sv (m)", value=1.50, step=0.10)
    Cobrimento_Nominal_cm = st.number_input("Cobrimento (cm)", value=3.0, step=0.5)
    
    st.header("2. Propriedades dos Materiais")
    fck_Concreto_MPa = st.number_input("fck do Concreto (MPa)", value=25.0, step=1.0)
    fy_Aco_MPa = st.number_input("fyk da Tela Soldada (MPa)", value=600.0, step=10.0)
    Kh_Solo_kNm3 = st.number_input("Coef. Mola do Solo (Kh - kN/m³)", value=25000.0, step=1000.0)
    
    st.header("3. Grampo e Perfuração")
    Diametro_Furo_m = st.number_input("Diâmetro do Furo (m)", value=0.10, step=0.01)
    Diametro_Barra_mm = st.number_input("Diâmetro da Barra (mm)", value=25.0, step=1.0)
    Aco_fyk_MPa = st.number_input("fyk da Barra (MPa)", value=500.0, step=10.0)
    Coeficiente_Seguranca_Aco = st.number_input("Coef. Segurança Aço (γs)", value=1.15, step=0.05)
    
    st.header("4. Corrosão (NBR 16920-2)")
    Agressividade_do_Meio = st.selectbox("Agressividade", ["Não Agressivo", "Agressivo (PH <= 5 ou Solo Orgânico)"])
    Tipo_de_Solo = st.selectbox("Tipo de Solo", ["Solos Naturais Inalterados", "Aterros Compactados", "Aterros Não Compactados"])
    Vida_Util = st.selectbox("Vida Útil", ["50 anos", "25 anos", "5 anos"])

# Banco de Dados de Corrosão
tabela_corrosao = {
    "Não Agressivo": {
        "Solos Naturais Inalterados": {"5 anos": 0.0, "25 anos": 0.30, "50 anos": 0.60},
        "Aterros Compactados": {"5 anos": 0.09, "25 anos": 0.35, "50 anos": 0.60},
        "Aterros Não Compactados": {"5 anos": 0.18, "25 anos": 0.70, "50 anos": 1.20}
    },
    "Agressivo (PH <= 5 ou Solo Orgânico)": {
        "Solos Naturais Inalterados": {"5 anos": 0.15, "25 anos": 0.75, "50 anos": 1.50},
        "Aterros Compactados": {"5 anos": 0.20, "25 anos": 1.00, "50 anos": 1.75},
        "Aterros Não Compactados": {"5 anos": 0.50, "25 anos": 2.00, "50 anos": 3.25}
    }
}

# ==========================================
# TELA PRINCIPAL (ESTRATIGRAFIA)
# ==========================================
st.subheader("Camadas de Solo (Estratigrafia e NSPT)")
st.write("Edite a tabela abaixo para adicionar as camadas do seu maciço:")

df_padrao = pd.DataFrame([
    {"Classe NBR": "Argilas e siltes argilosos", "Estado NBR": "Rija(o)", "Espessura (m)": 4.0, "NSPT Médio": 15},
    {"Classe NBR": "Areias e siltes arenosos", "Estado NBR": "Compacta(o)", "Espessura (m)": 6.0, "NSPT Médio": 20}
])

# Tabela interativa para o usuário editar
df_solos = st.data_editor(df_padrao, num_rows="dynamic", use_container_width=True)

# ==========================================
# MOTOR DE CÁLCULO E GERAÇÃO DE RELATÓRIO
# ==========================================
st.markdown("---")
if st.button("🚀 Processar Cálculo e Gerar Memorial (Word)", type="primary", use_container_width=True):
    with st.spinner("Executando Análise Numérica (MEF) e formatando memorial..."):
        
        # ---------------------------------------------------------
        # 1. MÓDULO GEOTÉCNICO (qs e bs)
        # ---------------------------------------------------------
        resultados = []
        FSp = 2.0
        profundidade_acumulada = 0.0
        
        for index, row in df_solos.iterrows():
            nspt = row["NSPT Médio"]
            espessura = row["Espessura (m)"]
            
            prof_inicial = profundidade_acumulada
            prof_final = profundidade_acumulada + espessura
            profundidade_acumulada = prof_final
            
            qs1 = qsd1 = qs2 = qsd2 = qsd_adotado = bs_kN_m = 0.0
            
            if nspt > 0:
                qs1 = 50 + (7.5 * nspt)
                qsd1 = qs1 / FSp
                qs2 = (45.12 * math.log(nspt)) - 14.99 if nspt > 1 else 0
                if qs2 < 0: qs2 = 0
                qsd2 = qs2 / FSp
                
                qsd_adotado = min(qsd1, qsd2)
                bs_kN_m = qsd_adotado * math.pi * Diametro_Furo_m
                
            resultados.append({
                "Trecho (m)": f"{prof_inicial:.1f} a {prof_final:.1f}",
                "Classe NBR": row["Classe NBR"],
                "Estado NBR": row["Estado NBR"],
                "NSPT Médio": nspt,
                "qsd1 (Ortigão)": round(qsd1, 2),
                "qsd2 (Springer)": round(qsd2, 2),
                "qsd Adotado (kPa)": round(qsd_adotado, 2),
                "bs (kN/m)": round(bs_kN_m, 2)
            })
            
        tabela_solos_md = "| Trecho (m) | Tipo de Solo (NBR) | NSPT | qsd Ortigão (kPa) | qsd Springer (kPa) | qsd Adotado (kPa) | bs (kN/m) |\n"
        tabela_solos_md += "|:---:|---|:---:|:---:|:---:|:---:|:---:|\n"
        for r in resultados:
            tabela_solos_md += f"| {r['Trecho (m)']} | {r['Classe NBR']} ({r['Estado NBR']}) | {r['NSPT Médio']} | {r['qsd1 (Ortigão)']} | {r['qsd2 (Springer)']} | **{r['qsd Adotado (kPa)']}** | **{r['bs (kN/m)']}** |\n"

        # ---------------------------------------------------------
        # 2. MÓDULO DO GRAMPO (Clouterre e Corrosão)
        # ---------------------------------------------------------
        t_sacrificio = tabela_corrosao[Agressividade_do_Meio][Tipo_de_Solo][Vida_Util]
        d_util = Diametro_Barra_mm - (2 * t_sacrificio)
        if d_util < 0: d_util = 0
        area_util_mm2 = (math.pi * (d_util ** 2)) / 4
        
        rtd_kN = (area_util_mm2 * Aco_fyk_MPa) / (Coeficiente_Seguranca_Aco * 1000)
        s_max = max(Espacamento_Sh_m, Espacamento_Sv_m)
        t0_kN = rtd_kN * (0.60 + 0.20 * (s_max - 1.0))

        # ---------------------------------------------------------
        # 3. MÓDULO DO PARAMENTO (MEF e Punção NBR 6118)
        # ---------------------------------------------------------
        q_pressao_kNm2 = t0_kN / (Espacamento_Sh_m * Espacamento_Sv_m)
        d_util_m = Espessura_Paramento_h_m - (Cobrimento_Nominal_cm / 100.0)
        
        ops.wipe()
        ops.model('basic', '-ndm', 3, '-ndf', 6)
        nx, ny = 15, 15
        dx, dy = Espacamento_Sh_m / nx, Espacamento_Sv_m / ny
        E_c = 4760 * math.sqrt(fck_Concreto_MPa) * 1000
        
        node_tag = 1
        for j in range(ny + 1):
            for i in range(nx + 1):
                x = i * dx - Espacamento_Sh_m/2
                y = j * dy - Espacamento_Sv_m/2
                ops.node(node_tag, x, y, 0.0)
                ops.fix(node_tag, 0, 0, 0, 0, 0, 1)
                ops.uniaxialMaterial('Elastic', node_tag, Kh_Solo_kNm3 * dx * dy)
                ops.element('zeroLength', node_tag+10000, node_tag, node_tag, '-mat', node_tag, '-dir', 3)
                node_tag += 1

        sec_tag = 1
        ops.section('ElasticMembranePlateSection', sec_tag, E_c, 0.2, Espessura_Paramento_h_m, 0.0)

        ele_tag = 1
        for j in range(ny):
            for i in range(nx):
                n1 = j * (nx + 1) + i + 1
                n2 = n1 + 1
                n3 = n2 + (nx + 1)
                n4 = n1 + (nx + 1)
                ops.element('ShellMITC4', ele_tag, n1, n2, n3, n4, sec_tag)
                ele_tag += 1

        ops.timeSeries('Linear', 1)
        ops.pattern('Plain', 1, 1)
        for i in range(1, ele_tag):
            ops.load(i, 0.0, 0.0, -q_pressao_kNm2 * dx * dy, 0.0, 0.0, 0.0)

        center_node = int(((ny/2) * (nx + 1)) + (nx/2) + 1)
        ops.fix(center_node, 1, 1, 1, 0, 0, 0)
        
        ops.system('UmfPack')
        ops.numberer('RCM')
        ops.constraints('Plain')
        ops.integrator('LoadControl', 1.0)
        ops.algorithm('Linear')
        ops.analysis('Static')
        ops.analyze(1)

        M_max_MEF = 0
        for i in range(1, ele_tag):
            forces = ops.eleResponse(i, 'force')
            if forces:
                mxx, myy = abs(forces[3]), abs(forces[4])
                if max(mxx, myy) > M_max_MEF:
                    M_max_MEF = max(mxx, myy)
        if M_max_MEF == 0:
            M_max_MEF = (q_pressao_kNm2 * max(Espacamento_Sh_m, Espacamento_Sv_m)**2) / 10

        # Dimensionamento da armadura
        bw_m = 1.0
        fcd_kN_m2 = (fck_Concreto_MPa / 1.4) * 1000.0
        fyd_aco_kN_m2 = (fy_Aco_MPa * 1000) / 1.15
        Md_MEF = M_max_MEF * 1.4
        Kmd_MEF = Md_MEF / (bw_m * (d_util_m**2) * fcd_kN_m2)

        if Kmd_MEF <= 0.259:
            kx_mef = (1 - math.sqrt(1 - 2.36 * Kmd_MEF)) / 1.18
            z_mef = d_util_m * (1 - 0.4 * kx_mef)
            As_MEF_cm2 = (Md_MEF / (z_mef * fyd_aco_kN_m2)) * 10000 
        else:
            As_MEF_cm2 = 999.0 # Valor indicativo de erro

        As_min = 0.0015 * bw_m * Espessura_Paramento_h_m * 10000 
        As_MEF_Final = max(As_MEF_cm2, As_min)

        # Punção
        Fsd = t0_kN * 1.4
        rho = (As_MEF_Final / 10000) / (bw_m * d_util_m)
        u_critico = 4 * Largura_Placa_bp_m + 2 * math.pi * (2 * d_util_m) 
        tau_Sd = Fsd / (u_critico * d_util_m)
        
        k_scale = 1 + math.sqrt(20 / (d_util_m * 100))
        if k_scale > 2.0: k_scale = 2.0
        tau_Rd1 = 0.13 * k_scale * ((100 * rho * fck_Concreto_MPa) ** (1/3)) * 1000
        
        if tau_Sd <= tau_Rd1:
            status_puncao = "OK (Concreto resiste sem estribos)"
        else:
            status_puncao = "FALHA NA TRAÇÃO DIAGONAL (Requer Armadura Transversal)"

        # ---------------------------------------------------------
        # 4. GERAÇÃO DO WORD VIA PANDOC
        # ---------------------------------------------------------
        markdown_texto = f"""
# MEMÓRIA DE CÁLCULO: CONTENÇÃO EM SOLO GRAMPEADO

**Elemento:** Dimensionamento Geotécnico e Estrutural
**Data da análise:** Gerado via Software Interativo

---

## 1. Parâmetros Geotécnicos e Adesão do Grampo ($b_s$)
A estimativa da tensão de cisalhamento última ($q_s$) entre a nata de cimento e o solo foi calculada a partir do $N_{{SPT}}$ médio de cada camada, utilizando os métodos empíricos de Ortigão (1997) e Springer (2006).

**Fórmulas Utilizadas:**
* **Ortigão (1997):** $$ q_{{s1}} = 50 + 7.5 \\cdot N_{{SPT}} \\quad \\text{{(kPa)}} $$
* **Springer (2006):** $$ q_{{s2}} = 45.12 \\cdot \\ln(N_{{SPT}}) - 14.99 \\quad \\text{{(kPa)}} $$

A tensão de projeto adotada ($q_{{sd}}$) para cada estrato corresponde ao menor valor obtido entre os dois métodos, dividido pelo Fator de Segurança ($FS_p = {FSp:.1f}$). 

A capacidade de carga ao arrancamento por metro linear ($b_s$) é calculada pelo perímetro do furo ($D = {Diametro_Furo_m * 100:.1f} \\text{{ cm}}$):
$$ b_s = q_{{sd}} \\cdot \\pi \\cdot D $$

{tabela_solos_md}
*(Nota: O valor de $b_s$ representa a resistência de cálculo ao arrancamento por metro linear do grampo, em kN/m).*

---

## 2. Dimensionamento Estrutural do Grampo (NBR 16920-2)
A capacidade de tração do grampo foi calculada prevendo a perda de seção por corrosão ao longo de {Vida_Util}.

**Cenário de Corrosão:** {Agressividade_do_Meio} | {Tipo_de_Solo}
* **Espessura de sacrifício tabelada ($t_s$):** {t_sacrificio:.2f} mm
* **Diâmetro nominal da barra:** {Diametro_Barra_mm:.2f} mm
* **Diâmetro útil após corrosão ($d_{{util}}$):** {d_util:.2f} mm

A resistência de cálculo à tração ($R_{{td}}$) é dada por:

$$ R_{{td}} = \\frac{{A_{{util}} \\cdot f_{{yk}}}}{{\\gamma_s}} = \\frac{{{area_util_mm2:.2f} \\cdot {Aco_fyk_MPa}}}{{{Coeficiente_Seguranca_Aco} \\cdot 1000}} = {rtd_kN:.2f} \\text{{ kN}} $$

**Carga na Cabeça do Grampo ($T_0$):**
Adotando o critério empírico de Clouterre (1991), onde $S_{{max}} = \\max(S_h, S_v) = {s_max:.2f} \\text{{ m}}$:

$$ T_0 = R_{{td}} \\cdot (0.60 + 0.20 \\cdot (S_{{max}} - 1.0)) = {t0_kN:.2f} \\text{{ kN}} $$

---

## 3. Dimensionamento do Paramento (Flexão e Punção)

### 3.1. Premissas Geométricas e Materiais
* **Espessura do paramento ($h$):** {Espessura_Paramento_h_m:.2f} m
* **Cobrimento nominal:** {Cobrimento_Nominal_cm:.1f} cm
* **Placa de ancoragem metálica ($b_p$):** {Largura_Placa_bp_m:.2f} m $\\times$ {Largura_Placa_bp_m:.2f} m
* **Concreto Projetado ($f_{{ck}}$):** {fck_Concreto_MPa:.1f} MPa
* **Aço da Tela Soldada ($f_{{yk}}$):** {fy_Aco_MPa:.1f} MPa

### 3.2. Análise Flexional Numérica (MEF)
Pela análise via Elementos Finitos (Placas Espessas de Mindlin-Reissner sobre apoios elásticos de Winkler, com $K_h = {Kh_Solo_kNm3:.0f} \\text{{ kN/m}}^3$), obteve-se:
* Momento Fletor Máximo de Cálculo: **{Md_MEF:.2f} kNm/m**
* Área de aço final adotada (respeitando a NBR 6118): **{As_MEF_Final:.2f} cm²/m**

### 3.3. Tensão Solicitante de Punção ($\\tau_{{Sd}}$)
O perímetro crítico ($u$) a $2d$ da face da placa de ancoragem ($d = {d_util_m*100:.1f} \\text{{ cm}}$):

$$ u = 4b_p + 2\\pi(2d) = 4({Largura_Placa_bp_m:.2f}) + 2\\pi(2 \\cdot {d_util_m:.3f}) = {u_critico:.2f} \\text{{ m}} $$

$$ \\tau_{{Sd}} = \\frac{{T_0 \\cdot \\gamma_f}}{{u \\cdot d}} = \\frac{{{t0_kN:.2f} \\cdot 1.4}}{{{u_critico:.2f} \\cdot {d_util_m:.3f}}} = {tau_Sd:.0f} \\text{{ kPa}} $$

### 3.4. Tensão Resistente do Concreto ($\\tau_{{Rd1}}$)
Considerando o efeito de escala ($k = {k_scale:.2f}$) e a taxa geométrica bidirecional da tela ($\\rho = {rho*100:.3f}\\%$):

$$ \\tau_{{Rd1}} = 0.13 \\cdot k \\cdot (100 \\cdot \\rho \\cdot f_{{ck}})^{{1/3}} \\cdot 1000 = {tau_Rd1:.0f} \\text{{ kPa}} $$

### 3.5. Diagnóstico Estrutural
**Resultado Final:** {status_puncao}
"""
        
        arquivo_docx = "Memoria_Calculo.docx"
        try:
            pypandoc.convert_text(markdown_texto, 'docx', format='md', outputfile=arquivo_docx)
            with open(arquivo_docx, "rb") as file:
                docx_bytes = file.read()
            
            # Remove o arquivo temporário do servidor/PC
            os.remove(arquivo_docx)
            
            # Feedback na tela
            st.success("✅ Cálculos finalizados! Baixe seu memorial no botão abaixo.")
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Carga no Grampo (T0)", f"{t0_kN:.1f} kN")
            col2.metric("Área de Aço MEF", f"{As_MEF_Final:.2f} cm²/m")
            col3.metric("Verificação de Punção", "APROVADO" if "OK" in status_puncao else "FALHA", delta_color="inverse")
            
            # Botão de Download do Word gerado
            st.download_button(
                label="📄 Baixar Memória de Cálculo (.docx)",
                data=docx_bytes,
                file_name="Memoria_Calculo_TIC_Trens.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

        except Exception as e:
            st.error(f"❌ Erro ao gerar o Word. O Pandoc está instalado no sistema? Detalhe: {e}")