cmake_minimum_required(VERSION 3.10)
project(FallDetection)

set(CMAKE_CXX_STANDARD 17)

# OpenCV
find_package(OpenCV REQUIRED)

# Mediapipe Setup
include_directories(
    /absolute/path/to/mediapipe
    /absolute/path/to/mediapipe/third_party
    /absolute/path/to/mediapipe/bazel-bin
)

# protobuf and abseil
find_package(Protobuf REQUIRED)

add_executable(fall_detection main.cpp fall_detection.cpp)

target_link_libraries(fall_detection
    ${OpenCV_LIBS}
    protobuf::libprotobuf
)
