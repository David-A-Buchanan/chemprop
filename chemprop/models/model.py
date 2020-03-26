from argparse import Namespace

import torch.nn as nn

from .mpn import MPN
from chemprop.nn_utils import get_activation_function, initialize_weights


class MoleculeModel(nn.Module):
    """A MoleculeModel is a model which contains a message passing network following by feed-forward layers."""

    def __init__(self, featurizer: bool, classification: bool, multiclass: bool):
        """
        Initializes the MoleculeModel.

        :param featurizer: Whether the model is a featurizer (i.e. no last layer).
        :param classification: Whether the model is a classification model.
        :param multiclass: Whether the model is a multiclass classification model.
        """
        super(MoleculeModel, self).__init__()

        assert not (classification and multiclass)

        self.featurizer = featurizer
        self.classification = classification
        self.multiclass = multiclass

        if self.featurizer:
            return

        if self.classification:
            self.sigmoid = nn.Sigmoid()

        if self.multiclass:
            self.multiclass_softmax = nn.Softmax(dim=2)

    def create_encoder(self, args: Namespace):
        """
        Creates the message passing encoder for the model.

        :param args: Arguments.
        """
        self.encoder = MPN(args)

    def create_ffn(self, args: Namespace):
        """
        Creates the feed-forward network for the model.

        :param args: Arguments.
        """
        if self.multiclass:
            self.num_classes = args.multiclass_num_classes
        if args.features_only:
            first_linear_dim = args.features_size
        else:
            first_linear_dim = args.hidden_size
            if args.use_input_features:
                first_linear_dim += args.features_dim

        dropout = nn.Dropout(args.dropout)
        activation = get_activation_function(args.activation)

        # Create FFN layers
        if args.ffn_num_layers == 1:
            ffn = [
                dropout,
                nn.Linear(first_linear_dim, args.output_size)
            ]
        else:
            ffn = [
                dropout,
                nn.Linear(first_linear_dim, args.ffn_hidden_size)
            ]
            for _ in range(args.ffn_num_layers - 2):
                ffn.extend([
                    activation,
                    dropout,
                    nn.Linear(args.ffn_hidden_size, args.ffn_hidden_size),
                ])

            if not self.featurizer:
                ffn.extend([
                    activation,
                    dropout,
                    nn.Linear(args.ffn_hidden_size, args.output_size),
                ])

        # Create FFN model
        self.ffn = nn.Sequential(*ffn)

    def featurize(self, *input):
        """
        Computes feature vectors of the input by leaving out the last layer.

        :param input: Input.
        :return: The feature vectors computed by the MoleculeModel.
        """
        fnn_without_last_layer = nn.Sequential(self.ffn[:-1])
        features = fnn_without_last_layer(self.encoder(*input))

        return features

    def forward(self, *input):
        """
        Runs the MoleculeModel on input.

        :param input: Input.
        :return: The output of the MoleculeModel.
        """
        output = self.ffn(self.encoder(*input))

        if self.featurizer:
            return output

        # Don't apply sigmoid during training b/c using BCEWithLogitsLoss
        if self.classification and not self.training:
            output = self.sigmoid(output)

        if self.multiclass:
            output = output.reshape((output.size(0), -1, self.num_classes))  # batch size x num targets x num classes per target
            if not self.training:
                output = self.multiclass_softmax(output)  # to get probabilities during evaluation, but not during training as we're using CrossEntropyLoss

        return output


def build_model(args: Namespace) -> nn.Module:
    """
    Builds a MoleculeModel, which is a message passing neural network + feed-forward layers.

    :param args: Arguments.
    :return: A MoleculeModel containing the MPN encoder along with final linear layers with parameters initialized.
    """
    output_size = args.num_tasks
    args.output_size = output_size
    if args.dataset_type == 'multiclass':
        args.output_size *= args.multiclass_num_classes

    model = MoleculeModel(
        featurizer=args.featurizer,
        classification=args.dataset_type == 'classification',
        multiclass=args.dataset_type == 'multiclass'
    )
    model.create_encoder(args)
    model.create_ffn(args)

    initialize_weights(model)

    return model
