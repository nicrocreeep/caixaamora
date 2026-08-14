import io
import re
import pdfplumber
from pypdf import PdfReader
import pytesseract
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Extrator de Nomes para Planilha", layout="wide")
st.title("📋 Extrator de Nomes para Planilha Excel")
st.write(
    "Envie um PDF consolidado (mesmo que seja imagem/scaneado). "
    "O sistema extrairá **todos os nomes** de cada página e gerará uma planilha Excel."
)

# Estado da sessão
if "excel_buffer" not in st.session_state:
    st.session_state.excel_buffer = None
if "df_resultado" not in st.session_state:
    st.session_state.df_resultado = None


def extrair_texto(page_plumber):
    """Tenta extrair texto nativo; se falhar ou for muito curto, usa OCR."""
    texto = page_plumber.extract_text() or ""
    texto_limpo = texto.strip().replace("\n", "").replace(" ", "")

    # Fallback OCR apenas se a página parecer escaneada/imagem
    if len(texto.strip()) < 20 or len(texto_limpo) < 10:
        try:
            img = page_plumber.to_image(resolution=300).original
            try:
                texto_ocr = pytesseract.image_to_string(img, lang="por")
            except Exception:
                texto_ocr = pytesseract.image_to_string(img, lang="eng")
            if len(texto_ocr.strip()) > len(texto.strip()):
                texto = texto_ocr
        except Exception:
            pass
    return texto


def extrair_nomes(texto):
    """Retorna uma lista com todos os nomes encontrados no texto da página."""
    if not texto:
        return []

    # Normaliza espaços e quebras de linha
    texto = re.sub(r"\s+", " ", texto)
    nomes_encontrados = []

    # ================================================================
    # PADRÃO 1 — Etiquetas de bloqueio / crachás / fichas
    # "NOME  GABRIEL DA COSTA ALVES  FUNÇÃO ..."
    # ================================================================
    padrao1 = (
        r"NOME\s+([A-Z][A-Z\s]+?)"
        r"(?=\s+FUN[ÇC][ÃA]O|\s+TEL[\s:]|\s+N[°º]|\s+CRACH[ÁA]|\s+[ÁA]REA|"
        r"\s+ESTOU|\s+PERIGO|\s+NÃO\s+LI|\s+ESTA\s+ETIQUETA|"
        r"\s+SÓ\s+PODEM|\s+REMOVIDOS|\s+PESSOA|\s+INDICADO|\s+VERSO|$)"
    )
    for match in re.finditer(padrao1, texto, re.IGNORECASE):
        nome = match.group(1).strip()
        # Corte de segurança
        for stop in ["FUNÇÃO", "FUNCAO", "TEL", "CRACHÁ", "CRACHA",
                     "ÁREA", "AREA", "ESTOU", "PERIGO", "NÃO", "NAO",
                     "LIGUE", "ESTA", "ETIQUETA", "SÓ", "PODEM", "REMOVIDOS",
                     "PESSOA", "INDICADO", "VERSO"]:
            nome = nome.split(stop)[0].strip()
        if 5 < len(nome) < 60 and len(nome.split()) >= 2:
            nomes_encontrados.append(nome)

    # ================================================================
    # PADRÃO 2 — Documentos de texto corrido (Termos, ASO, Contratos...)
    # "Eu, ALLISON CECILIO DE MATOS, CPF..."
    # ================================================================
    padrao2 = (
        r"Eu,\s*([A-Z][A-Z\s]+?)"
        r"(?=,\s*CPF|,\s*declaro|,\s*portador|,\s*autorizo|\s+colaborador|$)"
    )
    for match in re.finditer(padrao2, texto, re.IGNORECASE):
        nome = match.group(1).strip()
        for stop in ["COLABORADOR", "DECLARO", "TERMO", "EMPRESA", "INSTRUÇÕES", "CPF", "RG"]:
            nome = nome.split(stop)[0].strip()
        if 5 < len(nome) < 60 and len(nome.split()) >= 2:
            nomes_encontrados.append(nome)

    # ================================================================
    # PADRÃO 3 — Ficha Registro: "NOME FUNCIONÁRIO  FULANO DE TAL"
    # ================================================================
    padrao3 = r"NOME\s*FUNCION[ÁA]RIO\s+([A-Z][A-Z\s]+?)(?=\s+MATR[ÍI]CULA|\s+REGISTRO|$)"
    for match in re.finditer(padrao3, texto, re.IGNORECASE):
        nome = match.group(1).strip()
        if 5 < len(nome) < 60 and len(nome.split()) >= 2:
            nomes_encontrados.append(nome)

    # ================================================================
    # PADRÃO 4 — ASO / Contratos: "Nome: FULANO DE TAL  CPF: ..."
    # ================================================================
    padrao4 = (
        r"Nome\s*:\s*([A-Z][A-Z\s]+?)"
        r"(?=\s+CPF|\s+Cargo|\s+Fun[çc][ãa]o|\s+Admiss[ãa]o|\s+Idade|$)"
    )
    for match in re.finditer(padrao4, texto, re.IGNORECASE):
        nome = match.group(1).strip()
        if 5 < len(nome) < 60 and len(nome.split()) >= 2:
            nomes_encontrados.append(nome)

    # ================================================================
    # PADRÃO 5 — Ficha EPI: "COLABORADOR: FULANO DE TAL"
    # ================================================================
    padrao5 = r"COLABORADOR[:\s]+([A-Z][A-Z\s]+?)(?=\s+CHAPA|\s+Fun[çc][ãa]o|$)"
    for match in re.finditer(padrao5, texto, re.IGNORECASE):
        nome = match.group(1).strip()
        if 5 < len(nome) < 60 and len(nome.split()) >= 2:
            nomes_encontrados.append(nome)

    # Remove duplicatas mantendo a ordem de aparição
    return list(dict.fromkeys(nomes_encontrados))


# =============================================================================
# INTERFACE
# =============================================================================
arquivo = st.file_uploader("Selecione o PDF consolidado", type=["pdf"])

if arquivo is not None:
    if st.button("🔍 Extrair Nomes e Gerar Planilha", type="primary"):
        reader = PdfReader(arquivo)
        total = len(reader.pages)

        barra = st.progress(0)
        status = st.empty()

        dados = []

        with pdfplumber.open(arquivo) as pdf_plumber:
            for idx in range(total):
                page = pdf_plumber.pages[idx]
                texto = extrair_texto(page)
                nomes = extrair_nomes(texto)

                status.text(
                    f"Processando página {idx + 1}/{total} — "
                    f"{len(nomes)} nome(s) encontrado(s)"
                )

                for nome in nomes:
                    dados.append({"PÁGINA": idx + 1, "NOME": nome})

                barra.progress((idx + 1) / total)

        if dados:
            df = pd.DataFrame(dados)
            st.session_state.df_resultado = df

            # Gera Excel em memória
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Nomes")
            st.session_state.excel_buffer = excel_buffer.getvalue()

            st.success(f"✅ {len(dados)} nome(s) extraído(s) com sucesso!")
        else:
            st.warning("Nenhum nome encontrado no documento.")
            st.session_state.excel_buffer = None
            st.session_state.df_resultado = None

        status.empty()

# =============================================================================
# RESULTADO (persiste após recarregar)
# =============================================================================
if st.session_state.df_resultado is not None:
    st.subheader("📊 Pré-visualização")
    st.dataframe(st.session_state.df_resultado, use_container_width=True)

    st.download_button(
        label="⬇️ Baixar Planilha Excel (.xlsx)",
        data=st.session_state.excel_buffer,
        file_name="nomes_extraidos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
