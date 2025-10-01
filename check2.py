import streamlit as st
import pandas as pd
import datetime

# Lista de itens a verificar
itens = ["Etiqueta", "Tambor + Parafuso", "Solda", "Pintura", "Borracha ABS"]

# Usuários cadastrados
usuarios = {
    "joao": "1234",
    "maria": "abcd",
    "admin": "admin"
}

# Inicializar histórico na sessão para salvar todos checklists do dia
if "historico_checklists" not in st.session_state:
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

    caminho_foto = ""  # não está salvando a foto, pode implementar se quiser base64 ou outro método

    for item, info in resultados.items():
        dados.append({
            "Nº Série": serie,
            "Item": item,
            "Status": info['status'],
            "Observações": info['obs'],
            "Inspetor": usuario,
            "Data/Hora": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
            "Produto Reprovado": "Sim" if reprovado else "Não",
            "Reinspeção": "Sim" if reinspecao else "Não",
            "Foto Etiqueta": caminho_foto if item == "Etiqueta" else ""
        })

    df_novo = pd.DataFrame(dados)
    st.session_state["historico_checklists"] = pd.concat([df_existente, df_novo], ignore_index=True)

    # Gerar CSV para download
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
    else:
        st.info("Nenhum checklist registrado ainda para hoje.")

def novo_checklist():
    st.markdown("## ✅ Novo Checklist")
    serie = st.text_input("Nº de Série")
    data_atual = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')
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
                    file_name=f"Checklist_{serie}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
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
                        file_name=f"Checklist_Reinspecao_{serie_sel}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
    else:
        st.info("Nenhum produto reprovado para reinspeção.")

# --- Streamlit App ---
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


