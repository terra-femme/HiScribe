import tensorflow as tf


def build_model() -> tf.keras.Model:
    """
    TF/Keras classifier — predicts DOCTOR vs PATIENT from acoustic features.

    Input (6 features):
      [pitch_mean, pitch_variance, speaking_rate_wps,
       pause_ratio, avg_word_length, segment_duration_s]

    Output:
      probability of DOCTOR [0 = PATIENT, 1 = DOCTOR]

    Doctors tend to: speak faster, use technical vocabulary, ask directive questions.
    Patients tend to: describe sensations, hesitate, use lay language.

    Disagreements with diarization are flagged for provider review.
    """
    inputs = tf.keras.Input(shape=(6,), name='voice_features')
    x = tf.keras.layers.Dense(32, activation='relu')(inputs)
    x = tf.keras.layers.Dropout(0.2)(x)
    x = tf.keras.layers.Dense(16, activation='relu')(x)
    output = tf.keras.layers.Dense(1, activation='sigmoid', name='role')(x)

    model = tf.keras.Model(inputs=inputs, outputs=output)
    model.compile(
        optimizer='adam',
        loss='binary_crossentropy',
        metrics=['accuracy']
    )
    return model
