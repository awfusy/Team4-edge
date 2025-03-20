import pandas as pd
from sklearn.model_selection import train_test_split
import tensorflow as tf
from tensorflow.keras import layers, models


# Load the features and labels from the CSV file
data = pd.read_csv("features.csv")


# Separate features (all columns except 'label') and labels ('label' column)
X = data.drop(columns=["label"]).values  # Features
y = data["label"].values  # Labels

# Split into training, validation, and test sets
X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.3, random_state=42, stratify=y)
X_val, X_test, y_val, y_test = train_test_split(X_temp, y_temp, test_size=0.5, random_state=42, stratify=y_temp)

print(f"Training samples: {len(X_train)}")
print(f"Validation samples: {len(X_val)}")
print(f"Test samples: {len(X_test)}")


# Reshape the data to include a channel dimension (for CNN input)
input_shape = (128, X_train.shape[1] // 128, 1)  # Assuming 128 mel bands
X_train = X_train.reshape(-1, *input_shape)
X_val = X_val.reshape(-1, *input_shape)
X_test = X_test.reshape(-1, *input_shape)

# One-hot encode the labels
y_train = tf.keras.utils.to_categorical(y_train, num_classes=5)
y_val = tf.keras.utils.to_categorical(y_val, num_classes=5)
y_test = tf.keras.utils.to_categorical(y_test, num_classes=5)

# Build the CNN model
model = models.Sequential([
    layers.Input(shape=input_shape),  # Input shape depends on feature extraction
    layers.Conv2D(16, (3, 3), activation='relu'),
    layers.MaxPooling2D((2, 2)),
    layers.Conv2D(32, (3, 3), activation='relu'),
    layers.MaxPooling2D((2, 2)),
    layers.Flatten(),
    layers.Dense(64, activation='relu'),
    layers.Dense(5, activation='softmax')  # 32 classes (29 wake words + 3 noise)
])

# Compile the model
model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])



# Train the model
history = model.fit(
    X_train, y_train,
    validation_data=(X_val, y_val),
    epochs=20,
    batch_size=32
)

# Evaluate the model
test_loss, test_acc = model.evaluate(X_test, y_test)
print(f"Test Accuracy: {test_acc:.2f}")

# Convert to quantized TFLite model (reduces size + improves speed)
converter = tf.lite.TFLiteConverter.from_keras_model(model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.target_spec.supported_types = [tf.float16]  # FP16 quantization
tflite_quant_model = converter.convert()

with open('model_quant.tflite', 'wb') as f:
    f.write(tflite_quant_model)

print("TensorFlow Lite model saved as 'model_quant.tflite'")