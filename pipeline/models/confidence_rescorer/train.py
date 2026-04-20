"""
Training script for the confidence re-scorer.

Training data comes from the audit_log table:
  - Sessions where provider made NO corrections = high reliability labels
  - Sessions where provider edited segments = low reliability labels

Run: python -m models.confidence_rescorer.train
"""
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from db.sqlite import _conn
from models.confidence_rescorer.model import ConfidenceRescorer

SECTION_IDX = {'S': 0, 'O': 1, 'A': 2, 'P': 3}
WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), 'weights.pt')


class SegmentDataset(Dataset):
    def __init__(self):
        self.samples = []
        self._load_from_db()

    def _load_from_db(self):
        with _conn() as conn:
            # Approved sessions with no edits = reliable (label 1.0)
            approved = conn.execute('''
                SELECT s.segment_id, s.confidence, s.soap_section,
                       length(s.text) - length(replace(s.text, ' ', '')) + 1 AS token_count
                FROM segments s
                JOIN sessions sess ON s.session_id = sess.id
                WHERE sess.status = 'approved'
                AND s.segment_id NOT IN (
                    SELECT segment_id FROM audit_log WHERE event_type = 'segment_edited'
                )
            ''').fetchall()
            for row in approved:
                features = self._build_features(row['confidence'], row['token_count'], row['soap_section'])
                self.samples.append((features, 1.0))

            # Edited segments = lower reliability (label 0.3)
            edited = conn.execute('''
                SELECT s.segment_id, s.confidence, s.soap_section,
                       length(s.text) - length(replace(s.text, ' ', '')) + 1 AS token_count
                FROM segments s
                WHERE s.segment_id IN (
                    SELECT segment_id FROM audit_log WHERE event_type = 'segment_edited'
                )
            ''').fetchall()
            for row in edited:
                features = self._build_features(row['confidence'], row['token_count'], row['soap_section'])
                self.samples.append((features, 0.3))

    def _build_features(self, confidence: float, token_count: int, soap_section: str) -> list:
        onehot = [0.0] * 4
        idx = SECTION_IDX.get(soap_section or 'S', 0)
        onehot[idx] = 1.0
        return [float(confidence), float(token_count)] + onehot

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        features, label = self.samples[idx]
        return torch.tensor(features, dtype=torch.float32), torch.tensor([label], dtype=torch.float32)


def train(epochs: int = 50, lr: float = 1e-3):
    dataset = SegmentDataset()
    if len(dataset) == 0:
        print('[train] No training data found. Approve some sessions first.')
        return

    loader = DataLoader(dataset, batch_size=16, shuffle=True)
    model = ConfidenceRescorer()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.MSELoss()

    model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        for X, y in loader:
            optimizer.zero_grad()
            pred = model(X)
            loss = criterion(pred, y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        if (epoch + 1) % 10 == 0:
            print(f'[train] Epoch {epoch+1}/{epochs} — loss: {total_loss/len(loader):.4f}')

    torch.save(model.state_dict(), WEIGHTS_PATH)
    print(f'[train] Weights saved to {WEIGHTS_PATH}')


if __name__ == '__main__':
    train()
