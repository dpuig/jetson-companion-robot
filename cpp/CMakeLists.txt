cmake_minimum_required(VERSION 3.18)
project(robotics LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)  # for IntelliSense / clangd
# Orin = sm_87, Xavier = sm_72, original Nano = sm_53. "native" picks the local GPU.
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES native)
endif()

add_subdirectory(hello_cuda)
