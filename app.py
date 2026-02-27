import os
import chainlit as cl
import pandas as pd
from filelock import FileLock
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from openai import AsyncAzureOpenAI, RateLimitError, BadRequestError
from dotenv import load_dotenv

load_dotenv()

# Azure Configuration
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_API_KEY = os.getenv("AZURE_SEARCH_API_KEY")
AZURE_SEARCH_INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX_NAME")

MAX_HISTORY_MESSAGES = 2
TOP_N_RESULTS = 3
MAX_CONTENT_LENGTH = 1000  # Max characters per search result

DB_FILE = "580-W26-DB.xlsx"
DB_LOCK = "580-W26-DB.xlsx.lock"

if os.environ.get("CONTAINER_APP_NAME"):
    DB_FILE = f"/appdata/{DB_FILE}"
    DB_LOCK = f"/appdata/{DB_LOCK}"

# System prompt template
SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant for Cal Poly's CSC 580 course. 

IMPORTANT: You must ONLY discuss topics that are directly related to the class resources 
provided in a context block. Do not answer questions about unrelated topics, general
knowledge, or anything outside the scope of the course materials from a context block.
If a question is not related to the course content or cannot be answered using content
provided in a context block, politely explain that you can only help with CSC 580
course-related questions.

If the answer is not in a context block, say so.

--- BEGIN CONTEXT BLOCK ---
{context}
--- END CONTEXT BLOCK ---
"""

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
    raise ValueError("One or more environment variables are missing.")


async def get_search_client():
    credential = AzureKeyCredential(AZURE_SEARCH_API_KEY)
    return SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=AZURE_SEARCH_INDEX_NAME,
        credential=credential,
    )


async def search_documents(query: str, top: int = TOP_N_RESULTS):
    """Retrieve relevant documents from Azure AI Search."""
    client = await get_search_client()
    results = client.search(search_text=query, top=top)

    docs = []
    for result in results:
        uid = result["parent_id"] + "_" + result["chunk_id"]
        docs.append({"content": result["chunk"], "source": result["title"], "uid": uid})

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

    # Store the user in the session for token tracking
    user = cl.user_session.get("user")
    cl.user_session.set("user", user)

    # Initialize token tracking in session (not just user.metadata which doesn't persist)
    if user.identifier != "admin":
        cl.user_session.set("token_usage", user.metadata["token_usage"])
        cl.user_session.set("token_usage_limit", user.metadata["token_usage_limit"])

    # Initialize conversation history for multi-turn conversations
    cl.user_session.set("conversation_history", [])

    await cl.Message(
        content=(
            f"Welcome, {user.identifier}! I am an AI assistant intended to "
            "answer your questions about the CSC 580 course. "
            "Do not include any sensitive information."
        )
    ).send()


def get_enrolled_users():
    """Load enrolled usernames, passwords, and token usage info from the Excel file."""
    df = pd.read_excel(DB_FILE)
    df["username"] = df["Email"].str.replace("@calpoly.edu", "", regex=False)
    # Create a dict mapping username -> {password, token_usage_limit, token_usage}
    users = {}
    for _, row in df[df["username"] != ""].iterrows():
        users[row["username"]] = {
            "password": row["password"],
            "token_usage_limit": row["token_usage_limit"],
            "token_usage": row["token_usage"],
        }
    return users


def save_user_token_usage(username: str, token_usage: int):
    """Save the user's token usage to the DB file."""
    lock = FileLock(DB_LOCK, timeout=10)

    with lock:
        df = pd.read_excel(DB_FILE)
        df["username"] = df["Email"].str.replace("@calpoly.edu", "", regex=False)

        # Find the row for this user and update token_usage
        mask = df["username"] == username
        df.loc[mask, "token_usage"] = token_usage

        # Drop the temporary username column before saving
        df = df.drop(columns=["username"])
        df.to_excel(DB_FILE, index=False)


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    # Strip "@calpoly.edu" from username if present
    clean_username = username.replace("@calpoly.edu", "")

    # Admin login
    if (username, password) == ("admin", "admin"):
        return cl.User(
            identifier="admin", metadata={"role": "admin", "provider": "credentials"}
        )

    # Check if username is in the enrolled students list and password matches
    enrolled_users = get_enrolled_users()
    if (
        clean_username in enrolled_users
        and enrolled_users[clean_username]["password"] == password
    ):
        user_data = enrolled_users[clean_username]
        return cl.User(
            identifier=clean_username,
            metadata={
                "role": "student",
                "provider": "credentials",
                "token_usage_limit": user_data["token_usage_limit"],
                "token_usage": user_data["token_usage"],
            },
        )

    return None


@cl.on_message
async def main(message: cl.Message):
    """Handle incoming user messages."""
    openai_client = cl.user_session.get("openai_client")
    user = cl.user_session.get("user")

    # Skip token tracking for admin
    is_admin = user.identifier == "admin"

    # Check if user has exceeded their token limit
    token_usage = cl.user_session.get("token_usage") if not is_admin else 0
    token_usage_limit = (
        cl.user_session.get("token_usage_limit") if not is_admin else float("inf")
    )

    if not is_admin and token_usage >= token_usage_limit:
        await cl.Message(
            content=(
                "You have exceeded your token usage limit. "
                "Please talk to Professor Kurfess about getting more tokens."
            )
        ).send()
        return

    # 1. Retrieve context
    async with cl.Step(name="class resource search") as step:
        step.input = message.content
        docs = await search_documents(message.content)
        step.output = f"Found {len(docs)} relevant documents."

    conversation_history = cl.user_session.get("conversation_history", [])

    existing_sources = set()
    # Check last N user+assistant turns to avoid duplicates in context
    for msg in conversation_history[-MAX_HISTORY_MESSAGES * 2 :]:
        if "sources" in msg:
            for d in msg["sources"]:
                existing_sources.add(d["uid"])

    # Filter out docs that are already in conversation history
    docs = [d for d in docs if d["uid"] not in existing_sources]

    # Build context string with truncation
    def truncate(text: str, max_len: int = MAX_CONTENT_LENGTH) -> str:
        if len(text) <= max_len:
            return text
        return text[:max_len] + "... [truncated]"

    context_text = "\n\n".join(
        [f"Source: {d['source']}\nContent: {truncate(d['content'])}" for d in docs]
    )

    # 2. Construct Prompt
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context_text)

    # Get conversation history and build messages list
    messages = [{"role": "system", "content": system_prompt}]
    # Add all previous conversation turns
    messages.extend(conversation_history)
    # Add the current user message
    messages.append({"role": "user", "content": message.content})

    from pprint import pprint

    print("DEBUG:")
    pprint(messages)

    # 3. Call Azure OpenAI with streaming and usage tracking
    try:
        stream = await openai_client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
        )
    except RateLimitError:
        await cl.Message(
            content=(
                "The AI service is currently experiencing high demand. "
                "Please wait a minute and try again."
            )
        ).send()
        return
    except BadRequestError as e:
        if "context_length_exceeded" in str(e):
            # Clear conversation history and try again with just the current message
            cl.user_session.set("conversation_history", [])
            await cl.Message(
                content=(
                    "Your conversation has become too long. "
                    "I've cleared the history. Please try your question again."
                )
            ).send()
        else:
            await cl.Message(
                content=(
                    "There was an error processing your request. "
                    "Please try again or rephrase your question."
                )
            ).send()
        return

    # 4. Stream response and capture usage
    msg = await cl.Message(content="").send()
    total_tokens = 0
    assistant_response = ""
    async for part in stream:
        if part.usage:
            # Usage info comes in the final chunk
            total_tokens = part.usage.total_tokens
        elif part.choices:
            if token := part.choices[0].delta.content:
                assistant_response += token
                await msg.stream_token(token)

    # Track token usage after streaming completes
    if not is_admin and total_tokens > 0:
        new_token_usage = token_usage + total_tokens
        cl.user_session.set("token_usage", new_token_usage)

        # Save token usage to file after each message
        save_user_token_usage(user.identifier, new_token_usage)

    # 5. Update conversation history with this turn
    conversation_history.append({"role": "user", "content": message.content})
    conversation_history.append(
        {"role": "assistant", "content": assistant_response, "sources": docs}
    )
    cl.user_session.set("conversation_history", conversation_history)

    # 6. Append sources
    if docs:
        sources_text = "\n\n**Sources:**\n" + "\n".join(
            set([f"- {d['source']}" for d in docs])
        )
        await msg.stream_token(sources_text)

    await msg.update()
