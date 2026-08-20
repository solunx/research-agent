FROM python:3.12-slim

WORKDIR /app

# Persist browsers outside the default cache path
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1

# System libs Chromium needs (+ fonts for readable pages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    fonts-liberation \
    fonts-noto-color-emoji \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    libxshmfence1 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium + OS deps Playwright still needs
RUN playwright install --with-deps chromium \
    && playwright install-deps chromium || true

# Sanity check at build time (fails image build if browser missing)
RUN python -c "from playwright.sync_api import sync_playwright; \
p=sync_playwright().start(); \
b=p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage']); \
b.close(); p.stop(); print('Playwright Chromium OK')"

COPY . .

CMD ["python", "agent.py", "--help"]
