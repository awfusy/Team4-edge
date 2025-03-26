// fall_detection.hpp
#ifndef FALL_DETECTION_HPP
#define FALL_DETECTION_HPP

#include <opencv2/opencv.hpp>
#include <string>
#include <vector>
#include <mediapipe/framework/formats/landmark.pb.h>

float calculateDistance(cv::Point2f p1, cv::Point2f p2);
float calculateAngle(cv::Point2f a, cv::Point2f b, cv::Point2f c);
std::string classifyPatientState(const std::vector<mediapipe::NormalizedLandmark>& landmarks, cv::Size frame_size);
bool isPatientOnBed(cv::Point2f patient_center, cv::Rect bed_box);

#endif
