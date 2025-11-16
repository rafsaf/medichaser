FROM python:3.14-slim-trixie AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get -y update && apt-get -y install wget tini git nano vim procps screen bash-completion
RUN wget https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 -O /usr/bin/ttyd
RUN chmod +x /usr/bin/ttyd

RUN groupadd --gid 1000 medichaser && useradd -m --uid 1000 --gid 1000 -s /bin/bash medichaser

# Install Chrome and its dependencies
# Using a specific version of Chrome is often safer for consistency, but 'google-chrome-stable' is fine for general use.
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    libnss3 \
    libxss1 \
    libappindicator1 \
    fonts-liberation \
    libgbm-dev \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    # For headless Chrome specifically, if you encounter issues
    # xvfb # if using xvfb to run graphical applications
    # xauth # if using xvfb
    # Add Google Chrome repository
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable \
    # Clean up apt caches to reduce image size
    && rm -rf /var/lib/apt/lists/*

FROM base AS uv
COPY --from=ghcr.io/astral-sh/uv:0.9.2 /uv /uvx /bin/
COPY uv.lock pyproject.toml ./
RUN uv export --no-dev --no-hashes -o /requirements.txt --no-install-workspace --frozen
RUN uv export --only-group dev --no-hashes -o /requirements-dev.txt --no-install-workspace --frozen

FROM base AS app

COPY --from=uv /requirements.txt /requirements.txt
RUN pip install -r /requirements.txt

# this resolves permissions issues in local env
RUN mkdir -p /app/data && chmod 777 /app/data

RUN activate-global-python-argcomplete -y

USER medichaser

ENV PROMPT_COMMAND='history -a'
ENV HISTFILE=/app/data/.bash_history

WORKDIR /app

COPY medichaser.py notifications.py LICENSE ./

EXPOSE 7681
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["ttyd", "-W", "bash"]

FROM app AS tests
USER root
COPY --from=uv /requirements-dev.txt /requirements-dev.txt
RUN pip install -r /requirements-dev.txt
COPY pyproject.toml tests.py ./

ENTRYPOINT []
CMD ["pytest"]