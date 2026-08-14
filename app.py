import io
import re
import pdfplumber
from pypdf import PdfReader
import pytesseract
import streamlit as st
import pandas as pd
from PIL import Image

st.set_page_config(page_title="Extrator de Nomes para Planilha", layout="wide")
st.title("📋 Extrator de Nomes para Planilha Excel")
st.write(
    "Envie um PDF consolidado **ou imagens dos cartões**. "
    "O sistema extrairá **todos os nomes** e gerará uma planilha Excel."
)

if "excel_buffer" not in st.session_state:
    st.session_state.excel_buffer = None
if "df_resultado" not in st.session_state:
    st.session_state.df_resultado = None


def limpar_texto_corrompido(texto):
    """Remove caracteres triplicados do pdfplumber e normaliza."""
    if not texto:
        return ""
    # Reduz 3+ repetições do mesmo caractere para 1
    texto = re.sub(r'(.)\\1{2,}', r'\\1', texto)
    texto = re.sub(r'\\n+', ' ', texto)
    texto = re.sub(r'\\s+', ' ', texto)
    return texto.strip()


def extrair_nomes(texto):
    """Retorna TODOS os nomes encontrados no texto."""
    if not texto:
        return []

    texto = limpar_texto_corrompido(texto)
    nomes_encontrados = []

    # PADRÃO PRINCIPAL — Cartões de bloqueio
    # NÃO inclui "NOME" como delimitador! Isso evita parar em campos vazios.
    delimitadores = (
        r'FUN[ÇC][ÃA]O|FUNCAO|TEL[:\\s]|N[°º]?\\s*CRACH[ÁA]|CRACH[ÁA]'
        r'|[ÁA]REA|AREA|ESTOU|PERIGO|N[ÃA]O\\s*LIGUE|ESTA\\s*ETIQUETA'
        r'|S[ÓO]\\s*PODEM|REMOVIDOS|PESSOA|INDICADO|VERSO|$'
    )

    padrao = re.compile(
        rf'NOME\\s+([A-ZÀ-ÚÁÂÃÉÊÍÓÔÕÚÇ][A-ZÀ-ÚÁÂÃÉÊÍÓÔÕÚÇ\\s]+?)'
        rf'(?=\\s*(?:{delimitadores}))',
        re.IGNORECASE
    )

    for match in padrao.finditer(texto):
        nome = match.group(1).strip()
        nome = re.sub(r'\\s+', ' ', nome)
        # Filtros
        if 5 < len(nome) < 70 and len(nome.split()) >= 2:
            bloqueio = {
                'FUNCAO', 'FUNÇÃO', 'TEL', 'CRACHA', 'CRACHÁ',
                'AREA', 'ÁREA', 'ESTOU', 'PERIGO', 'LIGUE',
                'ETIQUETA', 'PODEM', 'REMOVIDOS', 'PESSOA', 'INDICADO', 'VERSO'
            }
            if not any(p in nome.upper() for p in bloqueio):
                nomes_encontrados.append(nome)

    # Remove duplicatas mantendo ordem
    return list(dict.fromkeys(nomes_encontrados))


def processar_pdf(arquivo):
    """Processa PDF com fallback OCR."""
    reader = PdfReader(arquivo)
    total = len(reader.pages)
    dados = []

    barra = st.progress(0)
    status = st.empty()

    with pdfplumber.open(arquivo) as pdf_plumber:
        for idx in range(total):
            page = pdf_plumber.pages[idx]
            
            # 1. Tenta texto nativo
            texto = page.extract_text() or ""
            nomes = extrair_nomes(texto)

            # 2. Se não achou nada, tenta OCR (página é imagem)
            if not nomes:
                try:
                    img = page.to_image(resolution=200).original
                    texto_ocr = pytesseract.image_to_string(img, lang="por")
                    nomes = extrair_nomes(texto_ocr)
                except Exception:
                    pass  # Se OCR falhar, ignora

            for nome in nomes:
                dados.append({"PÁGINA": idx + 1, "NOME": nome})

            status.text(
                f"Processando página {idx + 1}/{total} — "
                f"{len(nomes)} nome(s) encontrado(s) | Total: {len(dados)}"
            )
            barra.progress((idx + 1) / total)

    status.empty()
    return dados


def processar_imagens(arquivos_imagem):
    """Processa imagens individuais diretamente."""
    dados = []
    for idx, img_file in enumerate(arquivos_imagem):
        img = Image.open(img_file)
        texto_ocr = pytesseract.image_to_string(img, lang="por")
        nomes = extrair_nomes(texto_ocr)
        for nome in nomes:
            dados.append({"ARQUIVO": img_file.name, "NOME": nome})
    return dados


# =============================================================================
# INTERFACE
# =============================================================================
st.subheader("Opção 1: PDF Consolidado")
arquivo_pdf = st.file_uploader("Selecione o PDF", type=["pdf"], key="pdf")

st.subheader("Opção 2: Imagens dos Cartões")
arquivos_img = st.file_uploader(
    "Selecione as imagens (mais confiável para cartões escaneados)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
    key="imgs"
)

col1, col2 = st.columns(2)

with col1:
    if arquivo_pdf and st.button("🔍 Extrair do PDF", type="primary"):
        dados = processar_pdf(arquivo_pdf)
        if dados:
            df = pd.DataFrame(dados)
            st.session_state.df_resultado = df
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Nomes")
            st.session_state.excel_buffer = excel_buffer.getvalue()
            st.success(f"✅ {len(dados)} nome(s) extraído(s) do PDF!")
        else:
            st.warning("Nenhum nome encontrado no PDF.")
            st.info("💡 Dica: Se o PDF for escaneado, instale o Tesseract com idioma português.")

with col2:
    if arquivos_img and st.button("🔍 Extrair das Imagens", type="primary"):
        dados = processar_imagens(arquivos_img)
        if dados:
            df = pd.DataFrame(dados)
            st.session_state.df_resultado = df
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Nomes")
            st.session_state.excel_buffer = excel_buffer.getvalue()
            st.success(f"✅ {len(dados)} nome(s) extraído(s) das imagens!")
        else:
            st.warning("Nenhum nome encontrado nas imagens.")

# =============================================================================
# RESULTADO
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
