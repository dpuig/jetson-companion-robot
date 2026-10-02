// Smoke test: runs a vector add on the GPU and checks the result.
#include <cstdio>
#include <cuda_runtime.h>

#define CHECK(call)                                                           \
  do {                                                                        \
    cudaError_t err = (call);                                                 \
    if (err != cudaSuccess) {                                                 \
      std::fprintf(stderr, "%s:%d %s\n", __FILE__, __LINE__,                  \
                   cudaGetErrorString(err));                                  \
      return 1;                                                               \
    }                                                                         \
  } while (0)

__global__ void add(const float* a, const float* b, float* c, int n) {
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i < n) c[i] = a[i] + b[i];
}

int main() {
  cudaDeviceProp prop;
  CHECK(cudaGetDeviceProperties(&prop, 0));
  std::printf("GPU: %s (sm_%d%d)\n", prop.name, prop.major, prop.minor);

  const int n = 1 << 20;
  float *a, *b, *c;  // unified memory: CPU and GPU share DRAM on Jetson
  CHECK(cudaMallocManaged(&a, n * sizeof(float)));
  CHECK(cudaMallocManaged(&b, n * sizeof(float)));
  CHECK(cudaMallocManaged(&c, n * sizeof(float)));
  for (int i = 0; i < n; ++i) { a[i] = 1.0f; b[i] = 2.0f; }

  add<<<(n + 255) / 256, 256>>>(a, b, c, n);
  CHECK(cudaGetLastError());
  CHECK(cudaDeviceSynchronize());

  int bad = 0;
  for (int i = 0; i < n; ++i) bad += c[i] != 3.0f;
  std::printf("vector add of %d floats: %s\n", n, bad ? "FAILED" : "OK");

  cudaFree(a); cudaFree(b); cudaFree(c);
  return bad != 0;
}
