import torch
from model import MercuryNet, Encoder3D, Decoder, load_model
from tqdm import tqdm
from datetime import datetime
import os
import numpy as np
from AVSpeechDataset import AVSpeechDataset
from torch.utils.data import DataLoader
import json
from loss import MercuryNetLoss, HumanReadableLoss
import random
from hparams import hparams as hps
import argparse
import time

def train(model, device, train_dataloader, val_dataloader, optimizer, epochs):
    start = time.time()
    loss_func = MercuryNetLoss()
    human_readable_loss = HumanReadableLoss()
    human_readable_loss_list = []
    for epoch in range(epochs):
        
        train_batches = tqdm(enumerate(train_dataloader), total=len(train_dataloader), desc=f'Training for epoch {epoch}')
        start = time.time()
#         for _ in train_batches:
#             pass
#         print("Just load", time.time() - start)
        model.train()
        torch.cuda.empty_cache()
        for batch_idx, (data, target, metadata_embd) in train_batches:
#             print("D", time.time() - start)
#             start = time.time()
            data_mps = data.to(device)
            target_mps = target.to(device)
            metadata_embd_mps = metadata_embd.to(device)
#             print("A", time.time() - start)
            optimizer.zero_grad()
            output = model(data_mps, metadata_embd_mps)
            train_loss = loss_func(output, target_mps)
            train_loss.backward()
#             print("B", time.time() - start)
            optimizer.step()
#             print("C", time.time() - start)
        print("train loss:", train_loss)
        model.eval()
        torch.cuda.empty_cache()
        val_batches = tqdm(enumerate(val_dataloader), total=len(val_dataloader), desc=f'Validation for epoch {epoch}')
        this_epoch_loss = []
        for batch_idx, (data, target, metadata_embd) in val_batches:
            data_mps = data.to(device)
            target_mps = target.to(device)
            metadata_embd_mps = metadata_embd.to(device)
            output = model(data_mps, metadata_embd_mps)
            val_loss = loss_func(output, target_mps)
            this_epoch_loss.append(list(human_readable_loss(output, target_mps)))
        human_readable_loss_list.append(this_epoch_loss)
        print("val loss:", val_loss)
    

    checkpoint_path = f"model/checkpoints/ckpt_{datetime.today().strftime('%d_%H-%M')}.pt"
    
    torch.save(
        {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "iteration": epochs,
        },
        checkpoint_path,
    )
    np.save(f"model/checkpoints/valid_loss_{datetime.today().strftime('%d_%H-%M')}.npy", np.array(human_readable_loss_list))


def test(model, device, test_dataloader):
    loss_func = MercuryNetLoss()
    test_batches = tqdm(enumerate(test_dataloader),total=len(test_dataloader), desc='Testing model')
    human_readable_loss = HumanReadableLoss()
    human_readable_loss_list = []
    for batch_idx, (data, target, metadata_embd) in test_batches:
        data_mps = data.to(device)
        target_mps = target.to(device)
        metadata_embd_mps = metadata_embd.to(device)
        output = model(data_mps, metadata_embd_mps)
        test_loss = loss_func(output, target_mps)
        human_readable_loss_list.append(list(human_readable_loss(output, target_mps)))
    np.save(f"model/checkpoints/test_loss_{datetime.today().strftime('%d_%H-%M')}.npy", np.array(human_readable_loss_list))
    print("test loss:", test_loss)

def segment_data(root_dir, desired_datause):
    all_windows = np.load('data/all_windows.npy', allow_pickle=True)
    actual_datacount = min(len(all_windows), desired_datause)
    train_count = int(actual_datacount*0.7)
    val_count = int(actual_datacount*0.15)
    test_count = int(actual_datacount*0.15)
    total_count = train_count + val_count + test_count
    samples = random.sample([i for i in range(len(all_windows))], total_count)
    all_data = [all_windows[ix] for ix in samples]
    train_data = all_data[:train_count]
    val_data = all_data[train_count:train_count+val_count]
    test_data = all_data[train_count+val_count:]
    return train_data, val_data, test_data

def run_training_pass(root_dir, data_count=100, epochs=8, batch_size=16, ckpt_pth='model/checkpoints/lip2wav.pt'):
    encoder = Encoder3D(hps)
    decoder= Decoder()
    encoder_params = filter(lambda p: p.requires_grad, encoder.parameters())
    encoder_params = sum([np.prod(p.size()) for p in encoder_params])
    decoder_params = filter(lambda p: p.requires_grad, decoder.parameters())
    decoder_params = sum([np.prod(p.size()) for p in decoder_params])
    print("total trainable encoder weights:", encoder_params)
    print("total trainable decoder weights:", decoder_params)

    model, device = load_model(ckpt_pth)
    train_data, val_data, test_data = segment_data(root_dir, data_count)
    train_dataset = AVSpeechDataset(root_dir, train_data)
    val_dataset = AVSpeechDataset(root_dir, val_data)
    test_dataset = AVSpeechDataset(root_dir, test_data)
    train_dataloader = DataLoader(train_dataset, num_workers = 16, batch_size=batch_size, shuffle=True)
    val_dataloader = DataLoader(val_dataset, num_workers = 2,  batch_size=batch_size, shuffle=True)
    test_dataloader = DataLoader(test_dataset, num_workers = 2,  batch_size=batch_size, shuffle=True)

    optim = torch.optim.Adam(model.parameters())
    train(model, device, train_dataloader, val_dataloader, optim, epochs=epochs)
    test(model, device, test_dataloader)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='Training Model')
    parser.add_argument('-r', '--root_dir', help = 'Video directory', required=True)
    parser.add_argument('-c', '--count', help = 'How many windows to incldue in dataset', default=100)
    parser.add_argument('-b', '--batch_size', help = 'Batch Size', default=8)
    parser.add_argument('-e', '--epochs', help = 'Epochs', default=2)
    parser.add_argument('-cp', '--checkpoint', help = 'Checkpoint Location', default='model/checkpoints/lip2wav.pt')
    args = parser.parse_args()
    count = int(args.count)
    batch_size = int(args.batch_size)
    epochs = int(args.epochs)
    torch.autograd.set_detect_anomaly(True)
    start_time = time.time()
    run_training_pass(args.root_dir, data_count=count, batch_size=batch_size, epochs=epochs, ckpt_pth=args.checkpoint)
    print(f'Total training time for {epochs} epochs and {count} windows is {time.time() - start_time} seconds')

   