import os
import chainlit as cl
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from openai import AsyncAzureOpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Azure Configuration
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_API_KEY = os.getenv("AZURE_SEARCH_API_KEY")
AZURE_SEARCH_INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX_NAME")

# Initialization check
if not all(
    [
        AZURE_OPENAI_ENDPOINT,
        AZURE_OPENAI_API_KEY,
        AZURE_OPENAI_DEPLOYMENT_NAME,
        AZURE_SEARCH_ENDPOINT,
        AZURE_SEARCH_API_KEY,
        AZURE_SEARCH_INDEX_NAME,
    ]
):
    raise ValueError(
        "WARNING: One or more Azure environment variables are missing. Please check your .env file."
    )


async def get_search_client():
    credential = AzureKeyCredential(AZURE_SEARCH_API_KEY)
    return SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=AZURE_SEARCH_INDEX_NAME,
        credential=credential,
    )


async def search_documents(query: str, top: int = 3):
    """Retrieve relevant documents from Azure AI Search."""
    client = await get_search_client()
    results = client.search(search_text=query, top=top)

    docs = []
    for result in results:
        # Adapt this based on your actual index schema
        content = (
            result.get("content") or result.get("chunk") or result.get("text") or ""
        )
        source = result.get("source_url") or result.get("title") or "Unknown Source"
        docs.append({"content": content, "source": source})

    return docs


@cl.on_chat_start
async def start():
    """Initialize the chat session."""
    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
    )
    cl.user_session.set("openai_client", client)

    await cl.Message(
        content="Welcome! I am an AI assistant intended to answer your questions about the CSC 580 course. Ask me anything!"
    ).send()


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    # Fetch the user matching username from your database
    # and compare the hashed password with the value stored in the database
    if (username, password) == ("admin", "admin"):
        return cl.User(
            identifier="admin", metadata={"role": "admin", "provider": "credentials"}
        )
    else:
        return None


@cl.on_message
async def main(message: cl.Message):
    """Handle incoming user messages."""
    openai_client = cl.user_session.get("openai_client")

    # 1. Retrieve context
    msg = cl.Message(content="")
    await msg.send()

    # Notify user we are searching
    async with cl.Step(name="Azure AI Search") as step:
        step.input = message.content
        docs = await search_documents(message.content)

        # Build context string
        context_text = "\n\n".join(
            [f"Source: {d['source']}\nContent: {d['content']}" for d in docs]
        )

        step.output = f"Found {len(docs)} relevant documents."

    # 2. Construct Prompt
    system_prompt = f"""You are a helpful assistant. Use the following context to answer the user's question.
If the answer is not in the context, say so.

Context:
{context_text}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message.content},
    ]

    # 3. Call Azure OpenAI
    stream = await openai_client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT_NAME, messages=messages, stream=True
    )

    # 4. Stream response
    async for part in stream:
        if not part.choices:
            continue
        if token := part.choices[0].delta.content:
            await msg.stream_token(token)

    # 5. Append sources
    if docs:
        sources_text = "\n\n**Sources:**\n" + "\n".join(
            [f"- {d['source']}" for d in docs]
        )
        await msg.stream_token(sources_text)

    await msg.update()
