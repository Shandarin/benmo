# Benmo Worker

Python 3.12 workers for auditable causal-chain research, document capture, and deterministic verification.

Local smoke run (no API keys required):

```bash
python -m benmo_worker.cli run-stage full-analysis --input request.json --output result.json
python -m benmo_worker.cli consume --worker research --once
```

The default `BENMO_PROVIDER_MODE=stub` is deterministic and offline. Set it to `live` and configure
the provider keys described in `.env.example` to use OpenAI and external data APIs.

