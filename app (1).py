import io
import sqlite3
from datetime import datetime, date

import pandas as pd
import streamlit as st

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

st.set_page_config(
    page_title="Caixa da Padaria",
    page_icon="🥖",
    layout="wide",
)

DB_FILE = "padaria.db"


# =============================================================================
# BANCO DE DADOS
# =============================================================================

def conectar():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_banco():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            categoria TEXT,
            preco REAL NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT NOT NULL,
            forma_pagamento TEXT NOT NULL,
            total REAL NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS itens_venda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venda_id INTEGER NOT NULL,
            produto_id INTEGER NOT NULL,
            produto_nome TEXT NOT NULL,
            quantidade REAL NOT NULL,
            preco_unitario REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (venda_id) REFERENCES vendas(id),
            FOREIGN KEY (produto_id) REFERENCES produtos(id)
        )
    """)

    conn.commit()
    conn.close()


inicializar_banco()


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def moeda(valor):
    return (
        f"R$ {valor:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def buscar_produtos(apenas_ativos=True):
    conn = conectar()

    if apenas_ativos:
        query = """
            SELECT id, nome, categoria, preco, ativo
            FROM produtos
            WHERE ativo = 1
            ORDER BY nome
        """
    else:
        query = """
            SELECT id, nome, categoria, preco, ativo
            FROM produtos
            ORDER BY nome
        """

    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def cadastrar_produto(nome, categoria, preco):
    conn = conectar()

    try:
        conn.execute(
            """
            INSERT INTO produtos
                (nome, categoria, preco, ativo, criado_em)
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                nome.strip(),
                categoria.strip(),
                float(preco),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        sucesso = True
        mensagem = "Produto cadastrado com sucesso."
    except sqlite3.IntegrityError:
        sucesso = False
        mensagem = "Já existe um produto com esse nome."
    finally:
        conn.close()

    return sucesso, mensagem


def atualizar_preco_produto(produto_id, novo_preco):
    conn = conectar()
    conn.execute(
        "UPDATE produtos SET preco = ? WHERE id = ?",
        (float(novo_preco), int(produto_id)),
    )
    conn.commit()
    conn.close()


def desativar_produto(produto_id):
    conn = conectar()
    conn.execute(
        "UPDATE produtos SET ativo = 0 WHERE id = ?",
        (int(produto_id),),
    )
    conn.commit()
    conn.close()


def registrar_venda(carrinho, forma_pagamento):
    conn = conectar()

    try:
        total = sum(item["subtotal"] for item in carrinho)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO vendas (data_hora, forma_pagamento, total)
            VALUES (?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                forma_pagamento,
                total,
            ),
        )

        venda_id = cursor.lastrowid

        for item in carrinho:
            cursor.execute(
                """
                INSERT INTO itens_venda
                    (
                        venda_id,
                        produto_id,
                        produto_nome,
                        quantidade,
                        preco_unitario,
                        subtotal
                    )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    venda_id,
                    item["produto_id"],
                    item["produto_nome"],
                    item["quantidade"],
                    item["preco_unitario"],
                    item["subtotal"],
                ),
            )

        conn.commit()
        return venda_id

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def buscar_vendas(data_inicio, data_fim):
    conn = conectar()

    query = """
        SELECT
            v.id,
            v.data_hora,
            v.forma_pagamento,
            v.total
        FROM vendas v
        WHERE date(v.data_hora) BETWEEN ? AND ?
        ORDER BY v.data_hora DESC
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=(data_inicio.isoformat(), data_fim.isoformat()),
    )

    conn.close()
    return df


def buscar_itens_periodo(data_inicio, data_fim):
    conn = conectar()

    query = """
        SELECT
            iv.venda_id,
            v.data_hora,
            v.forma_pagamento,
            iv.produto_id,
            iv.produto_nome,
            iv.quantidade,
            iv.preco_unitario,
            iv.subtotal
        FROM itens_venda iv
        INNER JOIN vendas v ON v.id = iv.venda_id
        WHERE date(v.data_hora) BETWEEN ? AND ?
        ORDER BY v.data_hora DESC
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=(data_inicio.isoformat(), data_fim.isoformat()),
    )

    conn.close()
    return df


def buscar_resumo_produtos(data_inicio, data_fim):
    conn = conectar()

    query = """
        SELECT
            iv.produto_id,
            iv.produto_nome AS produto,
            SUM(iv.quantidade) AS quantidade_vendida,
            SUM(iv.subtotal) AS faturamento
        FROM itens_venda iv
        INNER JOIN vendas v ON v.id = iv.venda_id
        WHERE date(v.data_hora) BETWEEN ? AND ?
        GROUP BY iv.produto_id, iv.produto_nome
        ORDER BY faturamento DESC
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=(data_inicio.isoformat(), data_fim.isoformat()),
    )

    conn.close()
    return df


def gerar_excel(data_inicio, data_fim):
    produtos = buscar_produtos(apenas_ativos=False)
    vendas = buscar_vendas(data_inicio, data_fim)
    itens = buscar_itens_periodo(data_inicio, data_fim)
    resumo_produtos = buscar_resumo_produtos(data_inicio, data_fim)

    if not vendas.empty:
        # Agrupamento direto renomeando as agregações para evitar MultiIndex
        resumo_pagamentos = (
            vendas.groupby("forma_pagamento", as_index=False)
            .agg(
                **{
                    "Forma de Pagamento": ("forma_pagamento", "first"),
                    "Quantidade de Vendas": ("id", "count"),
                    "Faturamento": ("total", "sum"),
                }
            )
            .drop(columns=["forma_pagamento"])
        )
    else:
        resumo_pagamentos = pd.DataFrame(
            columns=[
                "Forma de Pagamento",
                "Quantidade de Vendas",
                "Faturamento",
            ]
        )

    resumo_geral = pd.DataFrame(
        {
            "Indicador": [
                "Período inicial",
                "Período final",
                "Quantidade de vendas",
                "Faturamento",
            ],
            "Valor": [
                data_inicio.strftime("%d/%m/%Y"),
                data_fim.strftime("%d/%m/%Y"),
                len(vendas),
                vendas["total"].sum() if not vendas.empty else 0,
            ],
        }
    )

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        resumo_geral.to_excel(writer, index=False, sheet_name="Resumo")
        resumo_pagamentos.to_excel(writer, index=False, sheet_name="Pagamentos")
        resumo_produtos.to_excel(
            writer, index=False, sheet_name="Produtos Vendidos"
        )
        vendas.to_excel(writer, index=False, sheet_name="Vendas")
        itens.to_excel(writer, index=False, sheet_name="Itens")
        produtos.to_excel(
            writer, index=False, sheet_name="Cadastro Produtos"
        )

    output.seek(0)
    return output.getvalue()


# =============================================================================
# ESTADO DA SESSÃO
# =============================================================================

if "carrinho" not in st.session_state:
    st.session_state.carrinho = []


# =============================================================================
# CABEÇALHO
# =============================================================================

st.title("🥖 Caixa da Padaria")
st.caption("Controle simples de produtos, vendas e formas de pagamento.")


# =============================================================================
# ABAS
# =============================================================================

aba_caixa, aba_produtos, aba_relatorio, aba_exportar = st.tabs(
    [
        "💰 Registrar Venda",
        "🥐 Produtos",
        "📊 Ver Vendas",
        "📁 Gerar Planilha",
    ]
)


# =============================================================================
# ABA 1 - REGISTRAR VENDA
# =============================================================================

with aba_caixa:
    st.subheader("Nova venda")

    produtos = buscar_produtos()

    if produtos.empty:
        st.warning(
            "Ainda não existem produtos cadastrados. "
            "Cadastre pelo menos um produto na aba '🥐 Produtos'."
        )
    else:
        mapa_produtos = {
            f"{row['nome']} — {moeda(row['preco'])}": row
            for _, row in produtos.iterrows()
        }

        col1, col2, col3 = st.columns([2.4, 1, 1])

        with col1:
            produto_selecionado = st.selectbox(
                "Produto",
                options=list(mapa_produtos.keys()),
            )

        produto_row = mapa_produtos[produto_selecionado]

        with col2:
            quantidade = st.number_input(
                "Quantidade",
                min_value=0.01,
                value=1.0,
                step=1.0,
            )

        with col3:
            preco_unitario = st.number_input(
                "Preço unitário",
                min_value=0.0,
                value=float(produto_row["preco"]),
                step=0.50,
            )

        if st.button(
            "➕ Adicionar ao carrinho",
            use_container_width=True,
        ):
            subtotal = float(quantidade) * float(preco_unitario)

            st.session_state.carrinho.append(
                {
                    "produto_id": int(produto_row["id"]),
                    "produto_nome": produto_row["nome"],
                    "quantidade": float(quantidade),
                    "preco_unitario": float(preco_unitario),
                    "subtotal": subtotal,
                }
            )

            st.success("Produto adicionado à venda.")

        st.divider()
        st.subheader("🛒 Carrinho")

        if not st.session_state.carrinho:
            st.info("Nenhum item adicionado ainda.")
        else:
            carrinho_df = pd.DataFrame(st.session_state.carrinho)

            exibicao = carrinho_df[
                [
                    "produto_nome",
                    "quantidade",
                    "preco_unitario",
                    "subtotal",
                ]
            ].rename(
                columns={
                    "produto_nome": "Produto",
                    "quantidade": "Qtd.",
                    "preco_unitario": "Preço",
                    "subtotal": "Subtotal",
                }
            )

            st.dataframe(
                exibicao,
                use_container_width=True,
                hide_index=True,
            )

            total_venda = sum(
                item["subtotal"]
                for item in st.session_state.carrinho
            )

            st.metric("Total da venda", moeda(total_venda))

            forma_pagamento = st.radio(
                "Forma de pagamento",
                ["PIX", "Débito", "Crédito", "Dinheiro"],
                horizontal=True,
            )

            col1, col2 = st.columns(2)

            with col1:
                if st.button(
                    "✅ Finalizar venda",
                    type="primary",
                    use_container_width=True,
                ):
                    venda_id = registrar_venda(
                        st.session_state.carrinho,
                        forma_pagamento,
                    )

                    st.session_state.carrinho = []

                    st.success(
                        f"Venda #{venda_id} registrada com sucesso!"
                    )
                    st.rerun()

            with col2:
                if st.button(
                    "🗑️ Limpar carrinho",
                    use_container_width=True,
                ):
                    st.session_state.carrinho = []
                    st.rerun()


# =============================================================================
# ABA 2 - PRODUTOS
# =============================================================================

with aba_produtos:
    st.subheader("Cadastro de produtos")

    with st.form("form_cadastro_produto", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            nome_produto = st.text_input(
                "Nome do produto",
                placeholder="Ex.: Pão francês",
            )

        with col2:
            categoria = st.text_input(
                "Categoria",
                placeholder="Ex.: Pães",
            )

        preco = st.number_input(
            "Preço de venda",
            min_value=0.0,
            value=0.0,
            step=0.50,
        )

        salvar_produto = st.form_submit_button(
            "💾 Cadastrar produto",
            use_container_width=True,
        )

    if salvar_produto:
        if not nome_produto.strip():
            st.error("Digite o nome do produto.")
        elif preco <= 0:
            st.error("Digite um preço maior que zero.")
        else:
            sucesso, mensagem = cadastrar_produto(
                nome_produto,
                categoria,
                preco,
            )

            if sucesso:
                st.success(mensagem)
                st.rerun()
            else:
                st.error(mensagem)

    st.divider()
    st.subheader("Produtos cadastrados")

    produtos_todos = buscar_produtos(apenas_ativos=False)

    if produtos_todos.empty:
        st.info("Nenhum produto cadastrado.")
    else:
        exibicao = produtos_todos.copy()

        exibicao["Situação"] = exibicao["ativo"].map(
            {1: "Ativo", 0: "Inativo"}
        )
        exibicao["Preço"] = exibicao["preco"].apply(moeda)

        exibicao = exibicao[
            ["id", "nome", "categoria", "Preço", "Situação"]
        ].rename(
            columns={
                "id": "ID",
                "nome": "Produto",
                "categoria": "Categoria",
            }
        )

        st.dataframe(
            exibicao,
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    ativos = buscar_produtos()

    if not ativos.empty:
        st.subheader("Atualizar produto")

        mapa_ids = {
            f"{row['id']} — {row['nome']}": row
            for _, row in ativos.iterrows()
        }

        produto_editar = st.selectbox(
            "Escolha o produto",
            list(mapa_ids.keys()),
        )

        row_editar = mapa_ids[produto_editar]

        novo_preco = st.number_input(
            "Novo preço",
            min_value=0.0,
            value=float(row_editar["preco"]),
            step=0.50,
        )

        col1, col2 = st.columns(2)

        with col1:
            if st.button(
                "💾 Atualizar preço",
                use_container_width=True,
            ):
                atualizar_preco_produto(
                    row_editar["id"],
                    novo_preco,
                )
                st.success("Preço atualizado.")
                st.rerun()

        with col2:
            if st.button(
                "🚫 Desativar produto",
                use_container_width=True,
            ):
                desativar_produto(row_editar["id"])
                st.success("Produto desativado.")
                st.rerun()


# =============================================================================
# ABA 3 - RELATÓRIOS
# =============================================================================

with aba_relatorio:
    st.subheader("Ver vendas")

    hoje = date.today()

    col1, col2 = st.columns(2)

    with col1:
        data_inicio = st.date_input(
            "Data inicial",
            value=hoje.replace(day=1),
        )

    with col2:
        data_fim = st.date_input(
            "Data final",
            value=hoje,
        )

    if data_inicio > data_fim:
        st.error("A data inicial não pode ser maior que a data final.")
    else:
        vendas = buscar_vendas(data_inicio, data_fim)

        total_faturado = vendas["total"].sum() if not vendas.empty else 0
        quantidade_vendas = len(vendas)
        ticket_medio = (
            total_faturado / quantidade_vendas
            if quantidade_vendas > 0
            else 0
        )

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Faturamento", moeda(total_faturado))

        with col2:
            st.metric("Quantidade de vendas", quantidade_vendas)

        with col3:
            st.metric("Ticket médio", moeda(ticket_medio))

        st.divider()

        if vendas.empty:
            st.info("Nenhuma venda encontrada nesse período.")
        else:
            st.subheader("Vendas")

            tabela_vendas = vendas.copy()
            tabela_vendas["total"] = tabela_vendas["total"].apply(moeda)

            tabela_vendas = tabela_vendas.rename(
                columns={
                    "id": "Venda",
                    "data_hora": "Data/Hora",
                    "forma_pagamento": "Pagamento",
                    "total": "Total",
                }
            )

            st.dataframe(
                tabela_vendas,
                use_container_width=True,
                hide_index=True,
            )

        st.divider()

        resumo_pagamentos = (
            vendas.groupby(
                "forma_pagamento",
                as_index=False
            )["total"].sum()
            if not vendas.empty
            else pd.DataFrame(columns=["forma_pagamento", "total"])
        )

        if not resumo_pagamentos.empty:
            st.subheader("💳 Vendas por forma de pagamento")

            resumo_pagamentos["total"] = (
                resumo_pagamentos["total"].apply(moeda)
            )

            resumo_pagamentos = resumo_pagamentos.rename(
                columns={
                    "forma_pagamento": "Pagamento",
                    "total": "Faturamento",
                }
            )

            st.dataframe(
                resumo_pagamentos,
                use_container_width=True,
                hide_index=True,
            )

        st.divider()

        resumo_produtos = buscar_resumo_produtos(
            data_inicio,
            data_fim,
        )

        if not resumo_produtos.empty:
            st.subheader("🥐 Produtos mais vendidos")

            resumo_produtos["faturamento"] = (
                resumo_produtos["faturamento"].apply(moeda)
            )

            resumo_produtos = resumo_produtos.rename(
                columns={
                    "produto": "Produto",
                    "quantidade_vendida": "Quantidade",
                    "faturamento": "Faturamento",
                }
            )

            st.dataframe(
                resumo_produtos,
                use_container_width=True,
                hide_index=True,
            )


# =============================================================================
# ABA 4 - EXPORTAÇÃO
# =============================================================================

with aba_exportar:
    st.subheader("📁 Gerar planilha")

    hoje = date.today()

    col1, col2 = st.columns(2)

    with col1:
        export_inicio = st.date_input(
            "Data inicial para exportação",
            value=hoje.replace(day=1),
            key="export_inicio",
        )

    with col2:
        export_fim = st.date_input(
            "Data final para exportação",
            value=hoje,
            key="export_fim",
        )

    if export_inicio > export_fim:
        st.error("A data inicial não pode ser maior que a data final.")
    else:
        st.write(
            "A planilha terá abas com resumo, pagamentos, produtos vendidos, "
            "vendas, itens e cadastro de produtos."
        )

        if st.button(
            "📊 Gerar Excel",
            type="primary",
            use_container_width=True,
        ):
            excel_bytes = gerar_excel(
                export_inicio,
                export_fim,
            )

            nome_arquivo = (
                f"caixa_padaria_"
                f"{export_inicio.strftime('%Y%m%d')}_"
                f"{export_fim.strftime('%Y%m%d')}.xlsx"
            )

            st.download_button(
                "⬇️ Baixar planilha Excel",
                data=excel_bytes,
                file_name=nome_arquivo,
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                use_container_width=True,
            )
