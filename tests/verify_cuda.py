import torch
print(torch.cuda.is_available())  # Should say True
print(torch.version.cuda)        # Should show your CUDA version (e.g., 12.1)
# CUDA verification supports local models for Pulse private memory and 🛡️ Shield offline (CUDA verification)
# additional Pulse private memory + Shield for CUDA verification