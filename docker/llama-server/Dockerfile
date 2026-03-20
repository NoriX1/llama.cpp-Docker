ARG CUDA_VERSION=12.4.0
ARG UBUNTU_VERSION=22.04

FROM nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION} AS build

ARG CUDA_ARCH=90
ARG LLAMA_CPP_REPO=https://github.com/ggml-org/llama.cpp.git
ARG LLAMA_CPP_REF=master

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        curl \
        git \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

RUN git init /src \
    && git -C /src remote add origin "${LLAMA_CPP_REPO}" \
    && git -C /src fetch --depth 1 origin "${LLAMA_CPP_REF}" \
    && git -C /src checkout --detach FETCH_HEAD

RUN if [ -n "${CUDA_ARCH}" ]; then \
      export CMAKE_CUDA_ARCH="-DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCH}"; \
    fi \
    && cmake -S /src -B /tmp/build \
      -DGGML_NATIVE=OFF \
      -DGGML_CUDA=ON \
      -DGGML_BACKEND_DL=ON \
      -DGGML_CPU_ALL_VARIANTS=OFF \
      -DLLAMA_BUILD_TESTS=OFF \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined \
      ${CMAKE_CUDA_ARCH:-} \
    && cmake --build /tmp/build --config Release --target llama-server -j"$(nproc)"

RUN mkdir -p /opt/llama/bin /opt/llama/lib \
    && cp /tmp/build/bin/llama-server /opt/llama/bin/ \
    && cp -P /tmp/build/bin/libllama.so* /opt/llama/bin/ \
    && cp -P /tmp/build/bin/libggml.so* /opt/llama/bin/ \
    && cp -P /tmp/build/bin/libggml-base.so* /opt/llama/bin/ \
    && cp -P /tmp/build/bin/libggml-cpu.so* /opt/llama/bin/ \
    && cp -P /tmp/build/bin/libggml-cuda.so* /opt/llama/bin/ \
    && cp -P /tmp/build/bin/libmtmd.so* /opt/llama/bin/ \
    && cp -P /tmp/build/bin/libllama.so* /opt/llama/lib/ \
    && cp -P /tmp/build/bin/libggml.so* /opt/llama/lib/ \
    && cp -P /tmp/build/bin/libggml-base.so* /opt/llama/lib/ \
    && cp -P /tmp/build/bin/libggml-cpu.so* /opt/llama/lib/ \
    && cp -P /tmp/build/bin/libggml-cuda.so* /opt/llama/lib/ \
    && cp -P /tmp/build/bin/libmtmd.so* /opt/llama/lib/

FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION} AS runtime

ARG LLAMA_CPP_REF=unknown

LABEL org.opencontainers.image.title="llama-server-cuda" \
      org.opencontainers.image.description="Minimal CUDA runtime image for llama.cpp server" \
      org.opencontainers.image.revision="${LLAMA_CPP_REF}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV LLAMA_CPP_REF="${LLAMA_CPP_REF}" \
    LD_LIBRARY_PATH="/opt/llama/lib:${LD_LIBRARY_PATH}"

WORKDIR /opt/llama

COPY --from=build /opt/llama/ /opt/llama/
COPY scripts/llama-server-entrypoint.sh /usr/local/bin/llama-server-entrypoint.sh
COPY scripts/llama-server-healthcheck.sh /usr/local/bin/llama-server-healthcheck.sh

RUN chmod +x /usr/local/bin/llama-server-entrypoint.sh /usr/local/bin/llama-server-healthcheck.sh

EXPOSE 8001

HEALTHCHECK --interval=120s --timeout=5s --start-period=10m --retries=3 CMD ["/usr/local/bin/llama-server-healthcheck.sh"]

ENTRYPOINT ["/usr/local/bin/llama-server-entrypoint.sh"]
