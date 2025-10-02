import streamlit as st
import pandas as pd
import datetime
import pytz
import plotly.graph_objects as go
from supabase import create_client
import os
from dotenv import load_dotenv
from pathlib import Path
import base64  # necessário para fotos em base64

# =============================
# Carregar variáveis de ambiente
# =============================
env_path = Path(__file__).parent / "teste.env"
load_dotenv(dotenv_path=env_path)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# =============================
# Configuração inicial
# =============================
TZ = pytz.timezone("America/Sao_Paulo")
itens = ["Etiqueta", "Tambor + Parafuso", "Solda", "Pintura", "Borracha ABS"]
usuarios = {"joao": "1234", "maria": "abcd", "admin": "admin"}

# =============================
# Funções de Banco (Supabase)
# =============================
def carregar_checklists():
    response = supabase.table("checklists").select("*").execute()
    df = pd.DataFrame(response.data)
    if not df.empty:
        df["data_hora"] = pd.to_datetime(df["data_hora"])
    return df

def salvar_checklist(serie, resultados, usuario, foto_etiqueta=None, reinspecao=False):
    # Checa duplicidade
    existe = supabase.table("checklists").select("numero_serie").eq("numero_serie", serie).execute()
    if not reinspecao and existe.data:
        st.error("⚠️ INVÁLIDO! DUPLICIDADE – Este Nº de Série já foi inspecionado.")
        return None

    reprovado = any(info['status'] == "Não Conforme" for info in resultados.values())
    data_hora = datetime.datetime.now(TZ)

    foto_base64 = None
    if foto_etiqueta is not None:
        try:
            foto_bytes = foto_etiqueta.getvalue()
            foto_base64 = base64.b64encode(foto_bytes).decode()
        except Exception as e:
            st.error(f"Erro ao processar a foto: {e}")
            foto_base64 = None

    for item, info in resultados.items():
        supabase.table("checklists").insert({
            "numero_serie": serie,
            "item": item,
            "status": info['status'],
            "observacoes": info['obs'],
            "inspetor": usuario,
            "data_hora": data_hora.isoformat(),
            "produto_reprovado": "Sim" if reprovado else "Não",
            "reinspecao": "Sim" if reinspecao else "Não",
            "foto_etiqueta": foto_base64 if item == "Etiqueta" else None
        }).execute()

    st.success(f"Checklist salvo no Supabase para o Nº de Série {serie}")
    return True

# =============================
# Funções do App
# =============================
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

# =============================
# Resumo com filtro de datas e Pareto
# =============================
def mostrar_resumo():
    df = carregar_checklists()
    if df.empty:
        st.info("Nenhum checklist registrado ainda.")
        return

    st.markdown("## 📊 Resumo de Inspeções")

    # Filtro por data
    min_data = df["data_hora"].min().date()
    max_data = df["data_hora"].max().date()
    data_inicial, data_final = st.date_input("Filtrar por Data", [min_data, max_data], min_value=min_data, max_value=max_data)

    # Filtra o dataframe
    df_filtrado = df[(df["data_hora"].dt.date >= data_inicial) & (df["data_hora"].dt.date <= data_final)]
    if df_filtrado.empty:
        st.info("Nenhum checklist registrado neste período.")
        return

    # Métricas
    total_inspecionados = df_filtrado["numero_serie"].nunique()
    total_aprovado = df_filtrado[df_filtrado["produto_reprovado"] == "Não"]["numero_serie"].nunique()
    total_reprovado = df_filtrado[df_filtrado["produto_reprovado"] == "Sim"]["numero_serie"].nunique()
    percentual_aprov = (total_aprovado / total_inspecionados * 100) if total_inspecionados > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Inspecionados", total_inspecionados)
    col2.metric("Total Aprovado", total_aprovado)
    col3.metric("Total Reprovado", total_reprovado)
    col4.metric("% Aprovado", f"{percentual_aprov:.1f}%")

    # Pareto das não conformidades
    mostrar_pareto(df_filtrado)

def mostrar_pareto(df):
    df_nc = df[df["status"] == "Não Conforme"]
    if df_nc.empty:
        st.info("Nenhuma não conformidade registrada neste período.")
        return

    pareto = df_nc["item"].value_counts().reset_index()
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

# =============================
# Novo Checklist (estável com camera_input)
# =============================
def novo_checklist():
    st.markdown("## ✅ Novo Checklist")
    serie = st.text_input("Nº de Série")
    data_atual = datetime.datetime.now(TZ).strftime('%d/%m/%Y %H:%M')
    st.write(f"Data/Hora: {data_atual}")

    resultados = {}

    # Inicializa foto na sessão para estabilidade
    if 'foto_etiqueta_temp' not in st.session_state:
        st.session_state['foto_etiqueta_temp'] = None

    for item in itens:
        st.markdown(f"### {item}")
        status = st.radio(f"Status - {item}", ["Conforme", "Não Conforme", "N/A"], key=f"novo_{item}")
        obs = st.text_area(f"Observações - {item}", key=f"obs_novo_{item}")
        if item == "Etiqueta":
            foto = st.camera_input("📸 Tire uma foto da Etiqueta")
            if foto is not None:
                st.session_state['foto_etiqueta_temp'] = foto
        resultados[item] = {"status": status, "obs": obs}

    if st.button("Salvar Checklist"):
        if not serie:
            st.error("Digite o Nº de Série!")
        elif st.session_state['foto_etiqueta_temp'] is None:
            st.error("⚠️ É obrigatório tirar foto da Etiqueta!")
        else:
            salvar_checklist(serie, resultados, st.session_state['usuario'], foto_etiqueta=st.session_state['foto_etiqueta_temp'])
            # Limpa a foto da sessão após salvar
            st.session_state['foto_etiqueta_temp'] = None

# =============================
# Reinspeção
# =============================
def reinspecao():
    df = carregar_checklists()

    if not df.empty:
        ultimos = df.sort_values("data_hora").groupby("numero_serie").tail(1)
        reprovados = ultimos[
            (ultimos["produto_reprovado"] == "Sim") & (ultimos["reinspecao"] == "Não")
        ]["numero_serie"].unique()
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
                salvar_checklist(serie_sel, resultados, st.session_state['usuario'], reinspecao=True)
    else:
        st.info("Nenhum produto reprovado para reinspeção.")

# =============================
# Histórico
# =============================
def mostrar_historico():
    df = carregar_checklists()
    if df.empty:
        st.info("Nenhum checklist registrado ainda.")
        return

    st.markdown("## 📚 Histórico de Checklists")
    
    col1, col2 = st.columns(2)
    with col1:
        filtro_usuario = st.selectbox("Filtrar por Inspetor", ["Todos"] + sorted(df["inspetor"].unique()))
    with col2:
        filtro_status = st.selectbox("Filtrar por Produto Reprovado", ["Todos", "Sim", "Não"])

    df_filtrado = df.copy()
    if filtro_usuario != "Todos":
        df_filtrado = df_filtrado[df_filtrado["inspetor"] == filtro_usuario]
    if filtro_status != "Todos":
        df_filtrado = df_filtrado[df_filtrado["produto_reprovado"] == filtro_status]

    df_filtrado = df_filtrado.sort_values("data_hora", ascending=False)

    st.dataframe(df_filtrado[[
        "data_hora", "numero_serie", "item", "status", "observacoes",
        "inspetor", "produto_reprovado", "reinspecao"
    ]], height=400)

    for idx, row in df_filtrado.iterrows():
        if row["item"] == "Etiqueta" and row["foto_etiqueta"]:
            st.markdown(f"**Nº Série: {row['numero_serie']}**")
            foto_bytes = base64.b64decode(row["foto_etiqueta"])
            st.image(foto_bytes, width=200)

# =============================
# Início do app
# =============================
st.set_page_config(page_title="Checklist de Qualidade", layout="wide")

if 'logged_in' not in st.session_state:
    login()
elif not st.session_state['logged_in']:
    login()
else:
    st.subheader(f"Checklist de Qualidade - Inspetor: {st.session_state['usuario']}")
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Resumo", "✅ Novo Checklist", "🔄 Reinspeção", "📚 Histórico"])
    with tab1:
        mostrar_resumo()
    with tab2:
        novo_checklist()
    with tab3:
        reinspecao()
    with tab4:
        mostrar_historico()
