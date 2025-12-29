import streamlit as st
import os
from google import genai
from pypdf import PdfReader
import faiss
import streamlit as st

# Importação correta do splitter
from langchain_text_splitters import RecursiveCharacterTextSplitter 
import numpy as np

# --- 1. Funções de Processamento do PDF (RAG) ---

# Geração de Embeddings e Armazenamento (Cache)

@st.cache_resource(show_spinner=False)

@st.cache_resource(show_spinner=False)
def processar_pdf_e_gerar_indice(pdf_file, api_key):
    client = genai.Client(api_key=api_key)
    
    # A. Extração do Texto (Omitido)
    pdf_reader = PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    
    # B. Chunking (Omitido)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, chunk_overlap=200, length_function=len
    )
    chunks = text_splitter.split_text(text) 
    
    # C. Geração de Embeddings com Batching
    st.info(f"Gerando embeddings para {len(chunks)} pedaços em lotes de 100...")
    
    embeddings_arrays = [] 
    BATCH_SIZE = 100
    
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        
        result = client.models.embed_content(
            model="text-embedding-004",
            contents=batch
        )
        
        # MUDANÇA CRÍTICA: Iteramos sobre a lista de objetos e convertemos cada um em float32
        # Isso garante que não haja objetos "ContentEmbedding"
        batch_embeddings = np.array([item.values for item in result.embeddings], dtype=np.float32)
        embeddings_arrays.append(batch_embeddings)
        
    # D. Armazenamento (FAISS - Índice Vetorial)
    embeddings = np.concatenate(embeddings_arrays, axis=0)
    
    if embeddings.ndim != 2:
        raise ValueError("O array de embeddings não tem o formato esperado (N, 768).")
    
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)
    
    return index, chunks

# --- 2. Função de Geração de Resposta (LLM) ---

def gerar_resposta_rag(pergunta_usuario, index, chunks, api_key):
    client = genai.Client(api_key=api_key)

    # 1. Embedding da Pergunta
    # CORREÇÃO 4: Acessando o vetor via .embedding (atributo do objeto)
    pergunta_embed_object = client.models.embed_content(
        model="text-embedding-004", 
        contents=pergunta_usuario
    )
    pergunta_vetor = np.array(
    pergunta_embed_object.embeddings[0].values, dtype=np.float32).reshape(1, -1)

    # 2. Busca no FAISS (Recuperação de Contexto)
    D, I = index.search(pergunta_vetor, k=3)
    
    contexto_relevante = [chunks[i] for i in I[0]]
    contexto_formatado = "\n---\n".join(contexto_relevante)

    # 3. Montar o Prompt com Contexto
    prompt = (
        f"Você é um assistente de estudos útil. Responda à PERGUNTA do usuário "
        f"de forma completa e clara, usando **apenas** o CONTEXTO fornecido.\n"
        f"Se a resposta não puder ser encontrada no contexto, diga gentilmente que "
        f"não tem a informação no material de estudo.\n\n"
        f"CONTEXTO:\n{contexto_formatado}\n\n"
        f"PERGUNTA: {pergunta_usuario}"
    )

    # 4. Chamar o Modelo Gemini
    response = client.models.generate_content(
        model="gemini-2.5-flash", 
        contents=prompt
    )
    
    return response.text

# --- 3. Interface Streamlit ---

st.set_page_config(page_title="🎓 Chatbot de Estudos com Gemini & PDF")

st.image("./images/banner.png", width=300)
st.title("📚 Chatbot de Estudos RAG")
st.caption("Aprenda com seu próprio material usando IA.")

# Configuração e Input da API Key
with st.sidebar:
    st.header("Configuração")

    api_key = st.text_input(
        "Sua Gemini API Key",
        type="password",
        help="Cole aqui sua chave da API Gemini"
    )

    st.markdown("---")

    # Texto UX personalizado (Opção 3)
    st.markdown("""
    <div style="
        padding: 12px;
        border-radius: 8px;
        background-color: #f5f7fb;
        margin-bottom: 8px;
        font-size: 14px;
    ">
        <strong>📄 Upload do material de estudos</strong><br>
        Arraste e solte um arquivo PDF abaixo ou clique em <em>Procurar arquivos</em>.
    </div>
    """, unsafe_allow_html=True)

    uploaded_file = st.file_uploader(
        label="",
        type=["pdf"]
    )


# Verifica se a API Key e o PDF estão presentes
if not api_key:
    st.warning("⚠️ Por favor, insira sua Gemini API Key na barra lateral para começar.")
    st.stop()

if uploaded_file:
    # Processa o PDF e armazena o índice (só roda na primeira vez ou se o PDF mudar)
    try:
        index, chunks = processar_pdf_e_gerar_indice(uploaded_file, api_key)
        st.sidebar.success(f"PDF ' {uploaded_file.name} ' processado! {len(chunks)} chunks criados.")
        st.session_state['pdf_processed'] = True
    except Exception as e:
        # Mensagem de erro unificada para falhas da API ou processamento
        st.error(f"Erro ao processar o PDF. Detalhes: {e}")
        st.session_state['pdf_processed'] = False
        st.stop()
else:
    st.info("Aguardando o upload de um PDF...")
    st.session_state['pdf_processed'] = False
    st.stop()

# Inicialização do Histórico do Chat (Opcional, mas melhora a UX)
if 'messages' not in st.session_state:
    st.session_state.messages = []

# Exibe mensagens anteriores
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Tratamento da Pergunta do Usuário
if prompt := st.chat_input("Pergunte algo sobre o seu material de estudo..."):
    # 1. Exibe a pergunta do usuário
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # 2. Gera a resposta RAG
    with st.spinner("Buscando e gerando resposta..."):
        try:
            response_text = gerar_resposta_rag(prompt, index, chunks, api_key)
        except Exception as e:
            response_text = f"Ops! Ocorreu um erro ao chamar o Gemini: {e}. Verifique sua API Key ou se há limite de uso."

    # 3. Exibe a resposta do assistente
    with st.chat_message("assistant"):
        st.markdown(response_text)
    
    # 4. Salva a resposta no histórico
    st.session_state.messages.append({"role": "assistant", "content": response_text})