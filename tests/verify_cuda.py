import torch
print(torch.cuda.is_available())  # Should say True
print(torch.version.cuda)        # Should show your CUDA version (e.g., 12.1)