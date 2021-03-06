import torch.nn as nn
from ..builder import HEADS
from .base import BaseHead

@HEADS.register_module
class TSNClsHead(BaseHead):

    def __init__(
        self,
        spatial_type='avg',
        spatial_size=7,
        consensus_cfg=dict(type='avg', dim=1),
        with_avg_pool=False,
        temporal_feature_size=1,
        spatial_feature_size=1,
        dropout_ratio=0.8,
        in_channels=1024,
        num_classes=101,
        init_std=0.001,
        fcn_testing=False,
    ):
        super(TSNClsHead, self).__init__(spatial_size, dropout_ratio,
                                         in_channels, num_classes, init_std)
        self.spatial_type = spatial_type
        self.consensus_type = consensus_cfg['type']
        self.temporal_feature_size = temporal_feature_size
        self.spatial_feature_size = spatial_feature_size
        self.cls_pool_size = (self.temporal_feature_size,
                              self.spatial_feature_size,
                              self.spatial_feature_size)
        self.with_avg_pool = with_avg_pool

        if self.consensus_type == 'avg':
            from .segmental_consensuses import SimpleConsensus
            self.segmental_consensus = SimpleConsensus(
                self.consensus_type, consensus_cfg['dim'])

        elif self.consensus_type in ['TRN', 'TRNmultiscale']:
            from .segmental_consensuses import return_TRN
            self.segmental_consensus = return_TRN(
                self.consensus_type, in_channels,
                consensus_cfg['num_frames'], num_classes)
        else:
            raise NotImplementedError

        if self.spatial_size == -1:
            self.pool_size = (1, 1)
            if self.spatial_type == 'avg':
                self.Logits = nn.AdaptiveAvgPool2d(self.pool_size)
            if self.spatial_type == 'max':
                self.Logits = nn.AdaptiveMaxPool2d(self.pool_size)
        else:
            self.pool_size = self.spatial_size
            if self.spatial_type == 'avg':
                self.Logits = nn.AvgPool2d(
                    self.pool_size, stride=1, padding=0)
            if self.spatial_type == 'max':
                self.Logits = nn.MaxPool2d(
                    self.pool_size, stride=1, padding=0)

        if self.with_avg_pool:
            self.avg_pool = nn.AvgPool3d(self.cls_pool_size)

        if self.consensus_type in ['TRN', 'TRNmultiscale']:
            img_feature_dim = 256
            self.new_fc = nn.Linear(self.in_channels, img_feature_dim)
        else:
            self.new_fc = nn.Linear(self.in_channels, self.num_classes)

        self.fcn_testing = fcn_testing
        self.new_cls = None

    def forward(self, x, num_seg):
        if not self.fcn_testing:
            x = self.Logits(x)
            if x.ndimension() == 4:
                x = x.unsqueeze(2)
            assert x.shape[1] == self.in_channels
            assert x.shape[2] == self.temporal_feature_size
            assert x.shape[3] == self.spatial_feature_size
            assert x.shape[4] == self.spatial_feature_size
            if self.with_avg_pool:
                x = self.avg_pool(x)
            if self.dropout is not None:
                x = self.dropout(x)

            x = x.view(x.size(0), -1)
            cls_score = self.new_fc(x)
            cls_score = cls_score.reshape((-1, num_seg) + cls_score.shape[1:])
            cls_score = self.segmental_consensus(cls_score)
            cls_score = cls_score.squeeze(1)
            return cls_score
        else:
            if self.new_cls is None:
                self.new_cls = nn.Conv3d(
                    self.in_channels,
                    self.num_classes,
                    1, 1, 0).cuda()
                self.new_cls.load_state_dict(
                    {'weight': self.new_fc.weight.unsqueeze(-1).unsqueeze(
                        -1).unsqueeze(-1),
                     'bias': self.new_fc.bias})
            class_map = self.new_cls(x)
            cls_score = class_map.mean([2, 3, 4])
            return cls_score

    def init_weights(self):
        nn.init.normal_(self.new_fc.weight, 0, self.init_std)
        nn.init.constant_(self.new_fc.bias, 0)
