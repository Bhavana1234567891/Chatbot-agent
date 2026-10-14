# Chatbot agent

Ask questions about one dress-ranking table. The agent checks the stored values, then runs SQL on a local DuckDB file.

The table is `products`: 8108 colorway rows loaded from `data/cit_national_ranks_cat30_dept2_3m.csv`. Tested with Python 3.14.

## What another person needs

Send the project folder. They need their own OpenAI key. Do not send your `.env`.

`data/products.duckdb` is the database. It already has the rows. Opening that file in an editor looks empty because DuckDB stores them in binary form, not as text.

If `products.duckdb` is missing, keep the CSV and run `python ingest.py` once. That rebuilds the database.

## Run on your machine

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create `.env` in this folder:

```
OPENAI_API_KEY=your-key-here
```

Terminal:

```powershell
python agent.py
```

One question:

```powershell
python agent.py which color of the AE corduroy dress ranks best
```

Type `quit` to leave the loop.

Browser:

```powershell
python -m streamlit run streamlit_app.py
```

Open the local URL that Streamlit prints. The page title is chatbot agent. Ask for a picture or a product link when you want one.

## Run with Docker

Start Docker Desktop first. From this folder:

```powershell
docker compose up --build
```

Compose reads `.env` and opens the app at http://localhost:8501. The image runs `ingest.py` on the CSV while it builds, so the container has its own copy of the database.

## Optional traces

Tracing stays off unless `.env` also has a LangSmith key. Use your own personal key (`lsv2_pt_`).

```
LANGCHAIN_API_KEY=your-langsmith-key
LANGCHAIN_PROJECT=fashion-ranking-agent
```
