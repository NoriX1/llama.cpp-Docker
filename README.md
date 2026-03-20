# llama.cpp + proxy в Docker Compose

Локальный OpenAI-compatible API для `llama.cpp` с NVIDIA CUDA и отдельным proxy-контейнером.

Особенности:

- GPU-вариант на `nvidia/cuda`
- модели хранятся вне image
- `llama-server` и proxy разделены по контейнерам
- запуск через `docker compose`
- `restart: unless-stopped`
- healthcheck для обоих сервисов
- логи доступны и через `docker logs`, и в файлах `./logs`

## Что в проекте

- [`compose.yaml`](compose.yaml)
- [`docker/llama-server/Dockerfile`](docker/llama-server/Dockerfile)
- [`docker/llama-proxy/Dockerfile`](docker/llama-proxy/Dockerfile)
- [`config/llama-server.args`](config/llama-server.args)
- [`config/llama-server.cpu-fallback.args`](config/llama-server.cpu-fallback.args)
- [`config/llama-proxy.py`](config/llama-proxy.py)
- [`scripts/llama-server-entrypoint.sh`](scripts/llama-server-entrypoint.sh)
- [`scripts/llama-proxy-entrypoint.sh`](scripts/llama-proxy-entrypoint.sh)

## Требования

- Docker Desktop или Docker Engine с Compose
- доступный NVIDIA GPU runtime для Docker
- GGUF-модель на хосте

## Быстрый старт

1. Подготовить `.env`:

```bash
cp .env.example .env
```

2. Проверить ключевые параметры в `.env`:

- `MODEL_DIR` — каталог с GGUF
- `MODEL_FILE` — файл модели
- `PROXY_PORT` — внешний порт proxy
- `LLAMA_SERVER_PORT` — внутренний порт `llama-server` внутри compose-сети
- `LLAMA_SERVER_PUBLIC_PORT` — внешний порт `llama-server` на хосте
- `LLAMA_GPU_MODE` — `required` или `fallback`
- `LLAMA_CPP_REF` — pinned commit `llama.cpp`
- `CUDA_ARCH` — архитектура CUDA вашего GPU

3. Убедиться, что модель существует:

```bash
ls -lh "${MODEL_DIR}/${MODEL_FILE}"
```

4. Собрать и запустить:

```bash
docker compose up -d --build
```

5. Проверить состояние:

```bash
docker compose ps
curl http://127.0.0.1:${LLAMA_SERVER_PUBLIC_PORT}/health
curl http://127.0.0.1:${PROXY_PORT}/health
```

## Использование сервиса

Основной endpoint:

- `http://127.0.0.1:${PROXY_PORT}/v1`

Диагностический endpoint `llama-server`:

- `http://127.0.0.1:${LLAMA_SERVER_PUBLIC_PORT}`

Пример запроса через proxy:

```bash
curl http://127.0.0.1:${PROXY_PORT}/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "local",
    "messages": [
      {"role": "user", "content": "Reply with exactly: ok"}
    ],
    "max_tokens": 8
  }'
```

Proxy автоматически:

- переписывает роли под совместимость с `llama.cpp`
- адаптирует tool calls для OpenClaw
- включает thinking mode по префиксу `[think]`

Пример thinking mode:

```json
{"role": "user", "content": "[think] кратко объясни, почему нужен prompt cache"}
```

## Как выбрать модель

Достаточно указать в `.env`:

```dotenv
MODEL_DIR=/path/to/models
MODEL_FILE=Qwen3.5-35B-A3B-Q4_K_M.gguf
```

Если модель нужно временно переключить без редактирования `.env`:

```bash
MODEL_FILE=another-model.gguf docker compose up -d
```

В контейнере модель будет доступна как:

```text
/models/${MODEL_FILE}
```

## Порты

По умолчанию:

- `11000` — proxy
- `11001` — `llama-server`

Чтобы изменить:

```dotenv
PROXY_PORT=9000
LLAMA_SERVER_PUBLIC_PORT=9001
```

## Логи

Через Docker:

```bash
docker compose logs -f llama-server
docker compose logs -f llama-proxy
```

Через файлы на хосте:

```bash
tail -f ./logs/llama-server.log
tail -f ./logs/llama-proxy.log
```

## Как проверить GPU

1. Проверить логи:

```bash
docker compose logs llama-server | rg "CUDA|load_backend|offloaded|Device 0"
```

2. Проверить запрос GPU у контейнера:

```bash
docker inspect $(docker compose ps -q llama-server) --format '{{json .HostConfig.DeviceRequests}}'
```

3. Проверить health:

```bash
curl http://127.0.0.1:${LLAMA_SERVER_PUBLIC_PORT}/health
```

При корректной работе в логах будут строки вида:

- `ggml_cuda_init: found ... CUDA devices`
- `load_backend: loaded CUDA backend`
- `offloaded ... layers to GPU`

## Важно про cold start

- первая загрузка большой модели может занимать несколько минут
- в это время `/health` у `llama-server` может отдавать `503`
- для этого в compose выставлен увеличенный `start_period=10m`
- регулярный healthcheck выполняется раз в 2 минуты, а не часто

## Fail-fast и fallback

Режим по умолчанию:

```dotenv
LLAMA_GPU_MODE=required
```

В этом режиме контейнер завершится с понятной ошибкой, если NVIDIA runtime внутри контейнера недоступен.

Если нужен осознанный CPU fallback:

```dotenv
LLAMA_GPU_MODE=fallback
```

Тогда будут использованы параметры из [`config/llama-server.cpu-fallback.args`](config/llama-server.cpu-fallback.args).

Для больших моделей CPU fallback обычно практически непригоден.

## Размеры

Фактические размеры image:

- `llama-server`: примерно `1.43 GiB`
- `llama-proxy`: примерно `43 MiB`

Отдельно:

- размер модели не входит в размер image
- размер model storage зависит только от GGUF-файла
- RAM/VRAM usage зависит от модели, кванта, контекста и runtime args

## Что хранится вне image

- GGUF-модель
- каталог `config/`
- каталог `logs/`

## Как обновить версию llama.cpp

В `.env`:

```dotenv
LLAMA_CPP_REPO=https://github.com/ggml-org/llama.cpp.git
LLAMA_CPP_REF=<commit-or-tag>
```

Затем:

```bash
docker compose build --no-cache llama-server
docker compose up -d
```

## Остановка и обновление

Остановить сервисы:

```bash
docker compose down
```

Перезапустить без пересборки:

```bash
docker compose restart
```

Пересобрать и поднять заново:

```bash
docker compose up -d --build
```

Обновить только proxy:

```bash
docker compose up -d --build llama-proxy
```

Обновить только `llama-server`:

```bash
docker compose up -d --build llama-server
```

## Частые проблемы

`/health` долго отдаёт `503` после старта:

- для больших GGUF-моделей это нормально на cold start
- дождись завершения загрузки модели и проверь `docker compose logs -f llama-server`

`llama-server` не стартует и пишет про NVIDIA runtime:

- проверь, что Docker действительно видит GPU
- проверь `docker inspect $(docker compose ps -q llama-server) --format '{{json .HostConfig.DeviceRequests}}'`

Proxy не поднимается:

- сначала проверь состояние `llama-server`
- proxy зависит от `service_healthy` у `llama-server`

Модель не находится:

- проверь `MODEL_DIR` и `MODEL_FILE` в `.env`
- проверь, что `ls -lh "${MODEL_DIR}/${MODEL_FILE}"` работает на хосте

Нужно переключить модель:

- измени `MODEL_FILE` или `MODEL_DIR` в `.env`
- затем выполни `docker compose up -d`
