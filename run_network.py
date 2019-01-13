import argparse

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from models import base_model
from models import models
from dataset import Dictionary, VQAFeatureDataset
from train import train
import os
import json


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data_root', type=str, default='/hdd/robik')
    parser.add_argument('--results_path', type=str, default='/hdd/robik/VQACP_results')

    parser.add_argument('--do_not_normalize_image_feats', action='store_true')

    parser.add_argument('--epochs', type=int, default=35)
    parser.add_argument('--num_hid', type=int, default=1024)
    parser.add_argument('--model', type=str, default='UpDn')
    parser.add_argument('--batch_size', type=int, default=64)
    parser.add_argument('--seed', type=int, default=1111, help='random seed')
    parser.add_argument('--answers_available', type=int, default=1, help='Are the answers available?')
    parser.add_argument('--mode', type=str, choices=['train', 'test'],
                        help='Checkpoint must be specified  for test mode', default='train')
    parser.add_argument('--w_emb_size', type=int, required=False, default=None)
    parser.add_argument('--dictionary_file', type=str, required=False, default=None)
    parser.add_argument('--glove_file', type=str, required=False, default=None)

    parser.add_argument('--spatial_feature_type')
    parser.add_argument('--spatial_feature_length', default=0, type=int)
    parser.add_argument('--h5_prefix', required=False, default='use_split', choices=['use_split', 'all'])
    parser.add_argument('--num_objects', required=False, type=int)
    parser.add_argument('--feature_subdir', required=False, default='features')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--resume_expt_dir', type=str)
    parser.add_argument('--resume_expt_name', type=str)
    parser.add_argument('--resume_expt_type', type=str, default='latest', choices=['best', 'latest'])

    parser.add_argument('--expt_name', type=str, required=True)

    parser.add_argument('--test', action='store_true')
    parser.add_argument('--test_split', type=str, default='val')
    parser.add_argument('--test_has_answers', action='store_true')
    parser.add_argument('--train_split', type=str, default='train')
    parser.add_argument('--token_length', type=int, default=20)
    args = parser.parse_args()

    args.dataroot = args.data_root
    args.answers_available = bool(args.answers_available)

    # Handle experiment save/resume
    if args.resume_expt_name is None:
        args.resume_expt_name = args.expt_name
    if args.resume_expt_dir is None:
        args.resume_expt_dir = args.results_path
    args.expt_resume_dir = os.path.join(args.resume_expt_dir, args.resume_expt_name)
    args.expt_save_dir = os.path.join(args.results_path, args.expt_name)

    if not os.path.exists(args.expt_save_dir):
        os.makedirs(args.expt_save_dir)

    args.vocab_dir = os.path.join(args.data_root, args.feature_subdir)
    args.feature_dir = os.path.join(args.data_root, args.feature_subdir)

    if args.dictionary_file is None:
        args.dictionary_file = args.vocab_dir + '/dictionary.pkl'
    if args.glove_file is None:
        args.glove_file = args.vocab_dir + '/glove6b_init_300d.npy'
    return args


def train_model():
    if not args.test:
        train_dset = VQAFeatureDataset(args.train_split, dictionary, data_root=args.dataroot, args=args)
    else:
        train_dset = None
    val_dset = VQAFeatureDataset(args.test_split, dictionary, data_root=args.dataroot, args=args)

    #constructor = 'build_%s' % args.model
    #model = getattr(base_model, constructor)(val_dset, args.num_hid, args.w_emb_size).cuda()
    #model.w_emb.init_embedding(args.glove_file)
    args.w_emb_size  = val_dset.dictionary.ntoken
    args.num_ans_candidates = val_dset.num_ans_candidates
    args.v_dim = val_dset.v_dim
    model = getattr(models, args.model)(args)

    model = nn.DataParallel(model).cuda()
    print("Our kickass model {}".format(model))

    optimizer = None
    epoch = 0
    best_val_score = 0
    best_epoch = 0

    if args.resume:
        resume_pth = os.path.join(args.expt_resume_dir, '{}-model.pth'.format(args.resume_expt_type))
        print('Loading %s' % resume_pth)
        model_data = torch.load(resume_pth)
        model.load_state_dict(model_data['model_state_dict'])
        optimizer = torch.optim.Adamax(filter(lambda p: p.requires_grad, model.parameters()))
        optimizer.load_state_dict(model_data['optimizer_state_dict'])
        epoch = model_data['epoch'] + 1
        best_val_score = float(model_data['best_val_score'])
        best_epoch = model_data['best_epoch']

    if not args.test:
        # TODO: For some reason, making num_workers > 1 retrieves gibberish data
        train_loader = DataLoader(train_dset, batch_size, shuffle=True, num_workers=1)
    else:
        train_loader = None
    eval_loader = DataLoader(val_dset, batch_size, shuffle=False, num_workers=1)

    train(model, train_loader, eval_loader, args.epochs, optimizer, args, epoch, best_val_score, best_epoch)

    if not args.test:
        train_dset.close_h5_file()
    val_dset.close_h5_file()


if __name__ == '__main__':
    args = parse_args()
    print("Running experiment with these parameters:")
    print(json.dumps(vars(args), indent=4))

    torch.manual_seed(args.seed)
    torch.cuda.manual_seed(args.seed)
    torch.backends.cudnn.benchmark = True

    dictionary = Dictionary.load_from_file(args.dictionary_file)

    batch_size = args.batch_size
    train_model()