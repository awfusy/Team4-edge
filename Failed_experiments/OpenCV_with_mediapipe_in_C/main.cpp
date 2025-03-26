#include <opencv2/opencv.hpp>
#include "mediapipe/framework/calculator_graph.h"
#include "mediapipe/framework/formats/image_frame.h"
#include "mediapipe/framework/formats/landmark.pb.h"
#include "mediapipe/framework/port/opencv_imgcodecs_inc.h"
#include "mediapipe/framework/port/opencv_video_inc.h"
#include "mediapipe/framework/port/file_helpers.h"
#include "fall_detection.hpp"

const std::string kInputStream = "input_video";
const std::string kOutputStream = "pose_landmarks";

int main() {
    // Load the MediaPipe Pose Tracking Graph
    mediapipe::CalculatorGraph graph;
    std::string graph_config_contents;
    mediapipe::file::GetContents("pose_tracking_graph.pbtxt", &graph_config_contents);
    mediapipe::CalculatorGraphConfig config = mediapipe::ParseTextProtoOrDie<mediapipe::CalculatorGraphConfig>(graph_config_contents);
    MP_RETURN_IF_ERROR(graph.Initialize(config));

    ASSIGN_OR_RETURN(mediapipe::OutputStreamPoller poller, graph.AddOutputStreamPoller(kOutputStream));
    MP_RETURN_IF_ERROR(graph.StartRun({}));

    // Open Webcam
    cv::VideoCapture cap(0);
    if (!cap.isOpened()) {
        std::cerr << "Error: Unable to open webcam.\n";
        return -1;
    }

    int frame_timestamp = 0;
    while (cap.isOpened()) {
        cv::Mat frame;
        cap >> frame;
        if (frame.empty()) break;

        // Convert frame to MediaPipe ImageFrame
        auto input_frame = absl::make_unique<mediapipe::ImageFrame>(
            mediapipe::ImageFormat::SRGB, frame.cols, frame.rows,
            mediapipe::ImageFrame::kDefaultAlignmentBoundary);
        cv::cvtColor(frame, mediapipe::formats::MatView(input_frame.get()), cv::COLOR_BGR2RGB);

        // Send frame to MediaPipe
        MP_RETURN_IF_ERROR(graph.AddPacketToInputStream(
            kInputStream, mediapipe::Adopt(input_frame.release())
                         .At(mediapipe::Timestamp(frame_timestamp++))));

        // Retrieve pose landmarks
        mediapipe::Packet packet;
        if (poller.Next(&packet)) {
            auto& landmarks = packet.Get<mediapipe::NormalizedLandmarkList>();

            // Convert landmarks into a vector of points
            std::vector<mediapipe::NormalizedLandmark> landmark_vec;
            for (int i = 0; i < landmarks.landmark_size(); i++) {
                landmark_vec.push_back(landmarks.landmark(i));
            }

            // Bed Box Simulation
            int bed_x1 = frame.cols / 4, bed_y1 = 0;
            int bed_x2 = 3 * frame.cols / 4, bed_y2 = frame.rows;
            cv::Rect bed_box(bed_x1, bed_y1, bed_x2 - bed_x1, bed_y2 - bed_y1);
            cv::rectangle(frame, bed_box, cv::Scalar(0, 0, 255), 2);
            cv::putText(frame, "Simulated Bed", cv::Point(bed_x1, 20), cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(0, 0, 255), 2);

            // Classify Patient State
            std::string state = classifyPatientState(landmark_vec, frame.size());

            // Compute Nose Position as Patient Center
            cv::Point2f patient_center(
                landmarks.landmark(mediapipe::PoseLandmark::NOSE).x * frame.cols,
                landmarks.landmark(mediapipe::PoseLandmark::NOSE).y * frame.rows
            );

            bool on_bed = isPatientOnBed(patient_center, bed_box);

            // Display Patient State
            std::string label;
            cv::Scalar color;
            if (on_bed) {
                if (state == "Laying Down") label = "Patient is Laying in Bed";
                else if (state == "Sitting") label = "Patient is Sitting on Bed";
                else if (state == "Standing") label = "Patient is Standing on Bed";
                else label = "Patient state Unknown";
                color = cv::Scalar(0, 255, 0);
            } else {
                if (state == "Laying Down") {
                    label = "Alert: Patient has fallen off Bed!";
                    color = cv::Scalar(0, 0, 255);
                } else {
                    label = "Patient is Standing (Off Bed)";
                    color = cv::Scalar(0, 255, 255);
                }
            }

            cv::putText(frame, label, cv::Point(50, 50), cv::FONT_HERSHEY_SIMPLEX, 0.7, color, 2);
        }

        // Display the frame
        cv::imshow("Fall Detection System", frame);

        // Exit if 'q' is pressed
        if (cv::waitKey(1) == 'q') break;
    }

    cap.release();
    cv::destroyAllWindows();
    return 0;
}
