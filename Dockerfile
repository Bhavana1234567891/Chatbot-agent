# Chatbot image. Pass OPENAI_API_KEY when the container starts.
FROM python:3.14-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY agent.py streamlit_app.py ingest.py ./
COPY prompt ./prompt
COPY tools ./tools
COPY data ./data

RUN python ingest.py

EXPOSE 8501

CMD ["python", "-m", "streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
