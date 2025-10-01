import streamlit as st
import pandas as pd
import datetime
import pytz
import os
import plotly.graph_objects as go

# Configurar fuso horário de São Paulo
TZ = pytz.timezone("America/Sao_Paulo")

# Lista de itens a verificar
itens = ["Etiqueta", "Tambor + Parafuso", "Solda", "Pintura", "Borracha ABS"]

# Usuários cadastrados
usuarios = {
    "joao": "1234",
    "maria": "abcd",
    "admin": "admin"
}

# Caminho do arquivo para salvar o histórico
ARQUIVO_CSV = "checklists.csv"

# Carregar histórico do CSV (ou criar vazio)
if "historico_checklists" not in st.session_state:
    try:
        st.session_state["historico_checklists"] = pd.read_csv(ARQUIVO_CSV)
    except FileNotFoundError:
        colunas = ["Nº Série", "Item", "Status", "Observações", "Inspetor", "Data/Hora", "Produto Reprovado", "Reinspeção", "Foto Etiqueta"]
        st.session_state["historico_checklists"] = pd.DataFrame(columns=colunas)

# --- Funções ---
def login():
    st.session_state['logged_in'] = False
    with st.form("login_form", clear_on_submit=False):
        st.subheader("Login")
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar")
        if submitted:
            if usuario in usuarios and usuarios[usuario] == senha:
                st.session_state['logged_in'] = True
                st.session_state['usuario'] = usuario
            else:
                st.error("Usuário ou senha inválidos!")

def salvar_checklist(serie, resultados, usuario, foto_etiqueta=None, reinspecao=False):
    df_existente = st.session_state["historico_checklists"]
    if not reinspecao and serie in df_existente["Nº Série"].unique():
        st.error("⚠️ INVÁLIDO! DUPLICIDADE – Este Nº de Série já foi inspecionado.")
        return None

    dados = []
    reprovado = any(info['status'] == "Não Conforme" for info in resultados.values())
    data_hora = datetime.datetime.now(TZ).strftime("%d/%m/%Y %H:%M")

    for item, info in resultados.items():
        dados.append({
            "Nº Série": serie,
            "Item": item,
            "Status": info['status'],
            "Observações": info['obs'],
            "Inspetor": usuario,
            "Data/Hora": data_hora,
            "Produto Reprovado": "Sim" if reprovado else "Não",
            "Reinspeção": "Sim" if reinspecao else "Não",
            "Foto Etiqueta": ""  # ainda não estamos salvando a foto
        })

    df_novo = pd.DataFrame(dados)
    st.session_state["historico_checklists"] = pd.concat([df_existente, df_novo], ignore_index=True)
    st.session_state["historico_checklists"].to_csv(ARQUIVO_CSV, index=False)
    csv_data = st.session_state["historico_checklists"].to_csv(index=False).encode('utf-8')
    st.success(f"Checklist salvo para o Nº de Série {serie}")
    return csv_data

def mostrar_resumo():
    df = st.session_state["historico_checklists"]
    if not df.empty:
        total_inspecionados = df["Nº Série"].nunique()
        total_aprovado = df[df["Produto Reprovado"] == "Não"]["Nº Série"].nunique()
        total_reprovado = df[df["Produto Reprovado"] == "Sim"]["Nº Série"].nunique()
        percentual_aprov = (total_aprovado / total_inspecionados * 100) if total_inspecionados > 0 else 0

        st.markdown("## 📊 Resumo do Dia")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Inspecionados", total_inspecionados)
        col2.metric("Total Aprovado", total_aprovado)
        col3.metric("Total Reprovado", total_reprovado)
        col4.metric("% Aprovado", f"{percentual_aprov:.1f}%")

        mostrar_pareto(df)
    else:
        st.info("Nenhum checklist registrado ainda.")

def mostrar_pareto(df):
    df_nc = df[df["Status"] == "Não Conforme"]
    if df_nc.empty:
        st.info("Nenhuma não conformidade registrada ainda.")
        return

    pareto = df_nc["Item"].value_counts().reset_index()
    pareto.columns = ["Item", "Quantidade"]
    pareto["% Acumulado"] = pareto["Quantidade"].cumsum() / pareto["Quantidade"].sum() * 100

    fig = go.Figure()
    fig.add_trace(go.Bar(x=pareto["Item"], y=pareto["Quantidade"], name="Quantidade", marker_color='indianred'))
    fig.add_trace(go.Scatter(x=pareto["Item"], y=pareto["% Acumulado"], name="% Acumulado", yaxis="y2"))

    fig.update_layout(
        title="Gráfico de Pareto - Não Conformidades",
        yaxis=dict(title="Quantidade"),
        yaxis2=dict(title="% Acumulado", overlaying="y", side="right", range=[0, 100]),
        xaxis=dict(title="Item"),
        legend=dict(x=0.85, y=1.15, orientation="h")
    )

    st.plotly_chart(fig)

def novo_checklist():
    st.markdown("## ✅ Novo Checklist")
    serie = st.text_input("Nº de Série")
    data_atual = datetime.datetime.now(TZ).strftime('%d/%m/%Y %H:%M')
    st.write(f"Data/Hora: {data_atual}")

    resultados = {}
    foto_etiqueta = None

    for item in itens:
        st.markdown(f"### {item}")
        status = st.radio(f"Status - {item}", ["Conforme", "Não Conforme", "N/A"], key=f"novo_{item}")
        obs = st.text_area(f"Observações - {item}", key=f"obs_novo_{item}")
        if item == "Etiqueta":
            foto_etiqueta = st.camera_input("📸 Tire uma foto da Etiqueta")
        resultados[item] = {"status": status, "obs": obs}

    if st.button("Salvar Checklist"):
        if not serie:
            st.error("Digite o Nº de Série!")
        elif foto_etiqueta is None:
            st.error("⚠️ É obrigatório tirar foto da Etiqueta!")
        else:
            csv_data = salvar_checklist(serie, resultados, st.session_state['usuario'], foto_etiqueta=foto_etiqueta)
            if csv_data:
                st.download_button(
                    label="📥 Baixar checklist CSV",
                    data=csv_data,
                    file_name=f"Checklist_{serie}_{datetime.datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )

def reinspecao():
    df = st.session_state["historico_checklists"]

    if not df.empty:
        # Considerar apenas o último registro de cada Nº de Série
        ultimos = df.sort_values("Data/Hora").groupby("Nº Série").tail(1)
        reprovados = ultimos[
            (ultimos["Produto Reprovado"] == "Sim") & (ultimos["Reinspeção"] == "Não")
        ]["Nº Série"].unique()
    else:
        reprovados = []

    if len(reprovados) > 0:
        st.markdown("## 🔄 Reinspeção de Produtos Reprovados")
        serie_sel = st.selectbox("Selecione o Nº de Série reprovado", reprovados)

        if serie_sel:
            resultados = {}
            for item in itens:
                st.markdown(f"### {item}")
                status = st.radio(f"Status - {item} (Reinspeção)", ["Conforme", "Não Conforme", "N/A"], key=f"re_{serie_sel}_{item}")
                obs = st.text_area(f"Observações - {item}", key=f"re_obs_{serie_sel}_{item}")
                resultados[item] = {"status": status, "obs": obs}

            if st.button("Salvar Reinspeção"):
                csv_data = salvar_checklist(serie_sel, resultados, st.session_state['usuario'], reinspecao=True)
                if csv_data:
                    st.download_button(
                        label="📥 Baixar checklist CSV (Reinspeção)",
                        data=csv_data,
                        file_name=f"Checklist_Reinspecao_{serie_sel}_{datetime.datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
    else:
        st.info("Nenhum produto reprovado para reinspeção.")

# --- Início do app ---
st.set_page_config(page_title="Checklist de Qualidade", layout="wide")

if 'logged_in' not in st.session_state:
    login()
elif not st.session_state['logged_in']:
    login()
else:
    st.subheader(f"Checklist de Qualidade - Inspetor: {st.session_state['usuario']}")
    tab1, tab2, tab3 = st.tabs(["📊 Resumo", "✅ Novo Checklist", "🔄 Reinspeção"])

    with tab1:
        mostrar_resumo()
    with tab2:
        novo_checklist()
    with tab3:
        reinspecao()

