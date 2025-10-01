import streamlit as st
import pandas as pd
import datetime
import pytz
import os

# Tenta importar o plotly com tratamento
try:
    import plotly.graph_objects as go
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

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
            "Foto Etiqueta": ""  # ainda não salvando imagem
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

        # --- Gráfico Pareto das falhas ---
        df_nao_conforme = df[df["Status"] == "Não Conforme"]

        if not df_nao_conforme.empty:
            st.markdown("### 📉 Pareto de Falhas (Não Conformidades)")

            if not PLOTLY_OK:
                st.warning("O módulo 'plotly' não está instalado. Para ver o gráfico de Pareto, adicione 'plotly' no requirements.txt ou instale localmente com `pip install plotly`.")
                return

            falhas_por_item = df_nao_conforme["Item"].value_counts().reset_index()
            falhas_por_item.columns = ["Item", "Quantidade"]
            falhas_por_item["% Acumulado"] = falhas_por_item["Quantidade"].cumsum() / falhas_por_item["Quantidade"].sum() * 100

            fig = go.Figure()

            fig.add_trace(go.Bar(
                x=falhas_por_item["Item"],
                y=falhas_por_item["Quantidade"],
                name="Quantidade de Falhas",
                marker_color="indianred",
                yaxis="y"
            ))

            fig.add_trace(go.Scatter(
                x=falhas_por_item["Item"],
                y=falhas_por_item["% Acumulado"],
                name="% Acumulado",
                yaxis="y2",
                mode="lines+markers",
                marker_color="black"
            ))

            fig.update_layout(
                title="Pareto das Falhas de Não Conformidade",
                xaxis=dict(title="Item"),
                yaxis=dict(title="Quantidade de Falhas"),
                yaxis2=dict(
                    title="% Acumulado",
                    overlaying="y",
                    side="right",
                    range=[0, 100],
                    showgrid=False
                ),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=500
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nenhuma falha de 'Não Conforme' registrada ainda.")
    else:
        st.info("Nenhum checklist registrado ainda.")

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
    reprovados = df[df["Produto Reprovado"] == "Sim"]["Nº Série"].unique() if not df.empty else []

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
