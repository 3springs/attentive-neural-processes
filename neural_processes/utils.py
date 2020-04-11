from pytorch_lightning.callbacks import EarlyStopping
from optuna.integration.pytorch_lightning import _check_pytorch_lightning_availability
from pathlib import Path
import numpy as np
import torch
import optuna


def init_random_seed(seed):
    # https://pytorch.org/docs/stable/notes/randomness.html
    np.random.seed(seed)
    torch.random.manual_seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False    


class PyTorchLightningPruningCallback(EarlyStopping):
    """Optuna PyTorch Lightning callback to prune unpromising trials.
    Example:
        Add a pruning callback which observes validation accuracy.
        .. code::
            trainer.pytorch_lightning.Trainer(
                early_stop_callback=PyTorchLightningPruningCallback(trial, monitor='avg_val_acc'))
    Args:
        trial:
            A :class:`~optuna.trial.Trial` corresponding to the current evaluation of the
            objective function.
        monitor:
            An evaluation metric for pruning, e.g., ``val_loss`` or
            ``val_acc``. The metrics are obtained from the returned dictionaries from e.g.
            ``pytorch_lightning.LightningModule.training_step`` or
            ``pytorch_lightning.LightningModule.validation_end`` and the names thus depend on
            how this dictionary is formatted.
    """

    def __init__(self, trial, monitor, **kwargs):
        # type: (optuna.trial.Trial, str) -> None

        super().__init__(monitor, **kwargs)

        _check_pytorch_lightning_availability()

        self._trial = trial
        self._monitor = monitor

    def on_epoch_end(self, trainer, pl_module):
        epoch = trainer.current_epoch
        logs = trainer.callback_metrics or {}
        current_score = logs.get(self._monitor)
        if current_score is None:
            return
        self._trial.report(current_score, step=epoch)
        if self._trial.should_prune():
            message = "Trial was pruned at epoch {}.".format(epoch)
            raise optuna.exceptions.TrialPruned(message)


class ObjectDict(dict):
    """
    Interface similar to an argparser
    """

    def __init__(self):
        pass

    def __setattr__(self, attr, value):
        self[attr] = value
        return self[attr]

    def __getattr__(self, attr):
        if attr.startswith("_"):
            # https://stackoverflow.com/questions/10364332/how-to-pickle-python-object-derived-from-dict
            raise AttributeError
        return dict(self)[attr]

    @property
    def __dict__(self):
        return dict(self)


def log_prob_sigma(value, loc, log_scale):
    """A slightly more stable (not confirmed yet) log prob taking in log_var instead of scale.
    modified from https://github.com/pytorch/pytorch/blob/2431eac7c011afe42d4c22b8b3f46dedae65e7c0/torch/distributions/normal.py#L65
    """
    var = torch.exp(log_scale * 2)
    return (
        -((value - loc) ** 2) / (2 * var) - log_scale - math.log(math.sqrt(2 * math.pi))
    )


def kl_loss_var(prior_mu, log_var_prior, post_mu, log_var_post):
    """
    Analytical KLD for two gaussians, taking in log_variance instead of scale ( given variance=scale**2) for more stable gradients
    
    For version using scale see https://github.com/pytorch/pytorch/blob/master/torch/distributions/kl.py#L398
    """

    var_ratio_log = log_var_post - log_var_prior
    kl_div = (
        (var_ratio_log.exp() + (post_mu - prior_mu) ** 2) / log_var_prior.exp()
        - 1.0
        - var_ratio_log
    )
    kl_div = 0.5 * kl_div
    return kl_div