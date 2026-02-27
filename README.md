# CSC x80 Assistant Agent

## Overview

This project is a **Retrieval-Augmented Generation (RAG)** AI assistant designed for Cal Poly's CSC 580 course. It allows enrolled students to ask questions about course materials (assignments, syllabus, textbook content) and receive AI-generated answers grounded in the actual course documents. The system includes user authentication, per-user token usage tracking, and is deployed as a containerized web application on Azure.

### Chainlit

Chainlit is the web framework used to build the conversational UI using Python. It provides a ChatGPT-like interface with support for:
- User authentication (`@cl.password_auth_callback`)
- Session management and conversation history
- Streaming responses from the LLM
- Multi-step visualization (e.g., showing "class resource search" step)

### app.py

The main application file containing all the core logic:
- **Authentication**: Password-based login for enrolled students (credentials stored in Excel DB) and admin users
- **RAG Pipeline**: Retrieves relevant documents from Azure AI Search, constructs a context-aware prompt, and streams responses from Azure OpenAI
- **Token Tracking**: Monitors and limits per-user token usage to manage API costs
- **Conversation History**: Maintains multi-turn conversation context (limited to recent messages to avoid context overflow)

#### Note on Conversation History

The Azure AI Search service exhibits a high recall (low precision), meaning it will often retrieve documents that are not relevant to the user's query.
This bloats the context window and increases token usage.
As a temporary measure, we only use the last 2 message exchanges to build the context for the next response.

### .env

Environment configuration file containing sensitive credentials and configuration:
- `AZURE_OPENAI_ENDPOINT`: LLM model endpoint URL
- `AZURE_OPENAI_API_KEY`: LLM model API key
- `AZURE_OPENAI_DEPLOYMENT_NAME`: LLM model deployment name
- `AZURE_OPENAI_API_VERSION`: Azure OpenAI LLM API version
- `AZURE_SEARCH_ENDPOINT`: Azure AI Search endpoint URL
- `AZURE_SEARCH_API_KEY`: Azure AI Search API key
- `AZURE_SEARCH_INDEX_NAME`: Azure AI Search index name
- `CHAINLIT_AUTH_SECRET`: Secret key for Chainlit's authentication system

### create_passwords.ipynb

A Jupyter notebook utility for managing the user database (`580-W26-DB.xlsx`):
- Generates unique 16-character alphanumeric passwords for each enrolled student
- Initializes/resets token usage limits (default: 3,000,000 tokens per user) and current usage counters

### Dockerfile

Defines the container image for deployment:
- Based on `python:3.12-slim`
- Installs dependencies from `requirements.txt`
    - `requirements.txt` should mirror `pixi.toml` (if you use pixi to manage dependencies)
- Runs Chainlit on port 8000

### pixi

[Pixi](https://pixi.sh/) is used for local development environment management. The `pixi.toml` file specifies:
- Python 3.12 as the base interpreter
- Conda dependencies
- PyPI dependencies (Chainlit, OpenAI SDK, Azure SDKs, pandas, etc.)

### requirements.txt

Python dependencies for Docker/pip-based installation, mirroring the `pixi.toml` PyPI dependencies plus OpenTelemetry packages for observability.

## Azure Resources

To set up this project with Azure, you will need to create the following resources.

### Foundry / Foundry Project

Azure AI Foundry (formerly Azure AI Studio) project for managing the AI models. This hosts the GPT deployment (e.g., `gpt-5.2-chat`) used for generating responses to student queries.

You'll need to create an LLM deployment and an embedding model deployment in Foundry. The embedding model deployment will be used for document embedding in the Azure AI Search index.

### (App Service) Domain

Custom domain configuration for the Container App, allowing the assistant to be accessed via a friendly URL (e.g., `csc580-assistant.com`) rather than the default Azure-generated domain.

### DNS Zone

Azure DNS Zone to manage DNS records for the custom domain, routing traffic to the Container App's IP address. You'll need to create a A record for the custom domain that points to the Container App's IP address. You'll also need to create a TXT record with the name `asuid` as instructed by Azure.

### Azure AI services multi-service account

A multi-service Azure Cognitive Services resource that provides access to AI "skills."
This is what allows you to chunk large documents to create embeddings for the Azure AI Search index (in Search Service).

### Search Service

Azure AI Search (formerly Azure Cognitive Search) instance for hosting the index. You will need to create an index (and set it's name in the environment variables). The index should be configured to use the embedding deployment from Foundry. You'll need to set up a skillset to chunk the documents and create embeddings for the index.

The AI Search service has a limit for document sizes. It will truncate any and all documents over the threshold. If a file is too large, it will deny its upload altogether. When a search is conducted, the entire document is retrieved and provided to the LLM.
So, for instance, if you were to include a whole textbook (although I doubt it'd fit as one document) it would be truncated to the limit, and be retrieved in its entirety.

My recommendation is manually breaking up documents like textbooks into separate documents, one per chapter or section.

### Storage Account

Azure Storage Account with Blob Storage and Azure Files share (`appdata-storage`) used for:
- Storing documents used for AI Search
- Persistent storage of the student database file (`580-W26-DB.xlsx`) across container restarts
- Mounted at `/appdata` in the container

#### Blob Storage

Blob storage is used to store the documents used for AI Search. You'll need to create a blob storage instance and set the connection string in the environment variables.

This must be done before creating the AI Search index. You select the blob storage instance when creating the index.

#### File Storage

File storage is used to store the Excel file used as a database for student authentication and usage limits. You'll need to create a file storage instance and properly mount it to the container at `/appdata`. The file storage is meant to be persistent across container restarts and updates.

Unfortunately, you need to mess around with the Azure container app service JSON settings to configure mounting the file storage to the container. 

### Container App

The Azure Container App running the Chainlit application:
- Name: `x80-assistant-app` (or whatever you want to name it)
- Configured with 1 CPU and 2GB memory (or whatever you want to configure)
- Auto-scales from 0 to 10 replicas based on demand
- Exposes port 8000 with HTTPS ingress

### Container Apps Environment

The managed environment (`x80-environment`) that hosts the Container App, providing networking, logging, and scaling infrastructure.

### Container Registry

Azure Container Registry (`x80registry.azurecr.io`) storing the Docker images for the application. Images are tagged (e.g., `chainlit-app:v1`) and pulled by the Container App during deployment.
