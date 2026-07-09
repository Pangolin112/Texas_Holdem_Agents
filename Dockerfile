# Portable image for the Texas Hold'em backend (webapp.py).
# Runs anywhere that takes a container: Hugging Face Spaces (Docker SDK,
# port 7860), Fly.io, Google Cloud Run, Railway, Render (Docker), ...
#
# The poker engine is pure standard-library Python; only the LLM opponents
# need the `openai` package (installed below) and an OPENAI_API_KEY, which you
# supply as a runtime secret in your host's dashboard — never bake it in.
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Hosts that inject $PORT (Render, Cloud Run, Fly) override this at runtime;
# Hugging Face Spaces expects the app on 7860.
ENV PORT=7860
EXPOSE 7860

CMD ["python", "webapp.py"]
