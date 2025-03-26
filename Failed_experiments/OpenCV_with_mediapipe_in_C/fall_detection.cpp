#include "fall_detection.hpp"
#include <cmath>

float calculateDistance(cv::Point2f p1, cv::Point2f p2) {
    return hypot(p1.x - p2.x, p1.y - p2.y);
}

float calculateAngle(cv::Point2f a, cv::Point2f b, cv::Point2f c) {
    cv::Point2f ba = a - b;
    cv::Point2f bc = c - b;
    float dot_product = ba.x * bc.x + ba.y * bc.y;
    float mag_ba = std::sqrt(ba.x * ba.x + ba.y * ba.y);
    float mag_bc = std::sqrt(bc.x * bc.x + bc.y * bc.y);
    float angle = std::acos(dot_product / (mag_ba * mag_bc));
    return angle * 180.0 / CV_PI;
}

std::string classifyPatientState(const std::vector<mediapipe::NormalizedLandmark>& landmarks, cv::Size frame_size) {
    auto toPixelCoords = [&](mediapipe::NormalizedLandmark lm) {
        return cv::Point2f(lm.x() * frame_size.width, lm.y() * frame_size.height);
    };

    cv::Point2f nose = toPixelCoords(landmarks[0]);
    cv::Point2f neck = toPixelCoords(landmarks[11]);
    cv::Point2f left_hip = toPixelCoords(landmarks[23]);
    cv::Point2f right_hip = toPixelCoords(landmarks[24]);
    cv::Point2f left_knee = toPixelCoords(landmarks[25]);
    cv::Point2f right_knee = toPixelCoords(landmarks[26]);

    cv::Point2f hips_mid = (left_hip + right_hip) * 0.5;
    cv::Point2f knees_mid = (left_knee + right_knee) * 0.5;
    float angle = calculateAngle(neck, hips_mid, knees_mid);

    if (angle > 160)
        return "Laying Down";
    else if (angle < 120)
        return "Sitting";
    else
        return "Standing";
}

bool isPatientOnBed(cv::Point2f patient_center, cv::Rect bed_box) {
    return bed_box.contains(patient_center);
}
