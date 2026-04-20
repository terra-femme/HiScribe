import torch
import torch.nn as nn


class ConfidenceRescorer(nn.Module):
    """
    PyTorch feedforward network — re-scores ASR segment reliability.

    Input (6 features):
      [asr_confidence, segment_token_count, soap_S, soap_O, soap_A, soap_P]
      soap_* are one-hot encoding of the mapped SOAP section

    Output:
      reliability score [0, 1]
      < 0.6 → flagged yellow in the review UI
    """

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(6, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid()
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)
