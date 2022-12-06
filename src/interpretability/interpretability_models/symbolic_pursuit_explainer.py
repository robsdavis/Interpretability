# stdlib
import sys
import os
import copy
from typing import Any, List, Tuple, Optional, Union
from abc import abstractmethod
import inspect

# third party
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
import sympy as smp  # We use sympy to display mathematical expresssions
from sklearn.metrics import (
    mean_squared_error,
    accuracy_score,
)  # we are going to assess the quality of the SymbolicRegressor based on the MSE
from PIL import Image

# Interpretability relative
from .utils import data
from .base import Explainer, Explanation

# Interpretability absolute
from interpretability.utils.pip import install
from interpretability.exceptions import exceptions

# symbolic-pursuit
for retry in range(2):
    try:
        # third party
        import symbolic_pursuit

        break
    except ImportError:
        depends = ["symbolic-pursuit"]
        install(depends)
from symbolic_pursuit import models


class SymbolicPursuitExplanation(Explanation):
    """
    The explanation object for symbolic pursuit
    """

    def __init__(
        self,
        expression,
        projections,
        x0: np.array,
        feature_importance: List,
        taylor_expansion: smp.core.add.Add,
        model_fit_quality: Optional[float] = None,
        fit_quality: Optional[float] = None,
    ) -> None:
        """Initialize the explanation object

        Args:
            expression (smp.core.add.Add): The symbolic expression of the model.
            projections (List): The projections in the symbolic expression.
            x0 (np.array):
            feature_importance (smp.core.add.Add): The feature importance produced by SymbolicPursuitExplainer.symbolic_model.get_feature_importance(x0).
            taylor_expansion (List): The taylor expansion produced by SymbolicPursuitExplainer.symbolic_model.get_taylor(x0, order).
            model_fit_quality (Optional[float]): The MSE score for the predictive model based on a test dataset. Needs measure_fit_quality() to be run. Defaults to None.
            fit_quality (Optional[float]): The MSE score for the symbolic model based on a test dataset. Needs measure_fit_quality() to be run. Defaults to None.

        """
        self.expression = expression
        self.projections = projections
        self.x0 = x0
        self.feature_importance = feature_importance
        self.taylor_expansion = taylor_expansion
        self.model_fit_quality = model_fit_quality
        self.fit_quality = fit_quality
        super().__init__()

    @staticmethod
    def name() -> str:
        return "Symbolic Pursuit Explanation"


class SymbolicPursuitExplainer(Explainer):
    def __init__(
        self, model: Any, X_explain: np.array, feature_names: List = [], *argv, **kwargs
    ) -> None:
        """
        SymbolicPursuitExplainer

        This explainer can take a very long time to fit. If fitting time is an issue there are several
        options you can pass to reduce it, such as increased `loss_tol` or reduced `patience`.

        Args:
            model (Any): The model to approximate.
            X_explain (np.array): The data used to fit the SymbolicRegressor.
            loss_tol:  The tolerance for the loss under which the pursuit stops. Defaults to 1.0e-3,
            ratio_tol: A new term is added only if new_loss / old_loss < ratio_tol. Defaults to 0.9,
            maxiter: Maximum number of iterations for optimization. Defaults to 100,
            eps: The smallest representable number such that 1.0 + eps != 1.0. Defaults to 1.0e-5,
            random_seed (int): The random seed for reproducibility. This is passed to . Defaults to 42,
            baselines (List): Defaults to list(load_h().keys()),
            task_type (str): Either the string "classification" or "regression". Defaults to "regression",
            patience (int) : A hard limit on the number of optimisation loops in fit(). Defaults to  10,
        """
        self.model = model
        self.X_explain = X_explain
        self.model_fit_quality = None
        self.fit_quality = None
        if feature_names:
            self.feature_names = feature_names
        else:
            self.feature_names = None

        super().__init__()

        smp.init_printing()
        self.symbolic_model = models.SymbolicRegressor(*argv, **kwargs)

    @staticmethod
    def name() -> str:
        return "symbolic_pursuit_explainer"

    @staticmethod
    def pretty_name() -> str:
        return "Symbolic Pursuit Explainer"

    def fit(self):
        """
        Fit the symbolic Regressor
        """
        # try to fit with numpy array (which works for some models e.g. sklearn models)
        for retry in range(2):
            try:
                self.symbolic_model.fit(self.model, self.X_explain)
                break
            # If that fails due to expecting a different type for X_explain try again with X_explain as a torch tensor
            # This works for pytorch models
            except TypeError:
                self.X_explain = torch.Tensor(self.X_explain)
        self.has_been_fit = True

    def measure_fit_quality(self, X_test: np.array, y_test: np.array):

        if self.has_been_fit:
            self.X_test = X_test
            self.y_test = y_test
            if self.symbolic_model.task_type == "classification":
                for retry in range(2):
                    try:
                        self.fit_quality = accuracy_score(
                            self.y_test, self.symbolic_model.predict(self.X_test)
                        )
                        break
                    except TypeError:
                        self.X_test = torch.Tensor(self.X_test)
                        self.y_test = torch.Tensor(self.y_test)
                for retry in range(2):
                    try:
                        self.model_fit_quality = accuracy_score(
                            self.y_test, self.model(self.X_test)
                        )
                        break
                    except TypeError:
                        self.X_test = torch.Tensor(self.X_test)
                        self.y_test = torch.Tensor(self.y_test)

                print(f"MSE score for the model: {self.model_fit_quality}")
                print(f"MSE score for the Symbolic Regressor: {self.fit_quality}")
            elif self.symbolic_model.task_type == "regression":
                for retry in range(2):
                    try:
                        self.fit_quality = mean_squared_error(
                            self.y_test, self.symbolic_model.predict(self.X_test)
                        )
                        break
                    except TypeError:
                        self.X_test = torch.Tensor(self.X_test)
                        self.y_test = torch.Tensor(self.y_test)
                for retry in range(2):
                    try:
                        self.model_fit_quality = mean_squared_error(
                            self.y_test, self.model(self.X_test)
                        )
                        break
                    except TypeError:
                        self.X_test = torch.Tensor(self.X_test)
                        self.y_test = torch.Tensor(self.y_test)

                print(f"MSE score for the model: {self.model_fit_quality}")
                print(f"MSE score for the Symbolic Regressor: {self.fit_quality}")
        else:
            raise exceptions.MeasureFitQualityCalledBeforeFit(self.has_been_fit)

    def explain(
        self, x0: np.array = None, taylor_expansion_order: int = 2
    ) -> pd.DataFrame:
        """
        The function to get the explanation data from the explainer
        """
        if self.has_been_fit:
            expression = self.symbolic_model.get_expression()
            projections = self.symbolic_model.get_projections()
            feature_importance = self.symbolic_model.get_feature_importance(x0)
            taylor_expansion = self.symbolic_model.get_taylor(
                x0, taylor_expansion_order
            )
            self.explanation = SymbolicPursuitExplanation(
                expression,
                projections,
                x0,
                feature_importance,
                taylor_expansion,
                self.model_fit_quality,
                self.fit_quality,
            )
            return self.explanation
        else:
            raise exceptions.ExplainCalledBeforeFit(self.has_been_fit)

    def summary_plot(self, file_prefilx="symbolic_pursuit", show=True, save_folder="."):
        """
        Plot the latex'ed equations if latex installed
        """
        if show:
            try:
                save_path_stem = os.path.abspath(save_folder)
                save_path_stem = os.path.join(save_path_stem, file_prefilx)
                smp.preview(
                    self.explanation.expression,
                    viewer="file",
                    filename=save_path_stem + "_expression.png",
                    dvioptions=["-D", "1200"],
                )
                smp.preview(
                    self.explanation.projections,
                    viewer="file",
                    filename=save_path_stem + "_projections.png",
                    dvioptions=[
                        "-D",
                        "1200",
                    ],  # TODO: Find optimum value
                )
                expression_img = Image.open(save_path_stem + "_expression.png")
                projection_img = Image.open(save_path_stem + "_projections.png")
                expression_img.show()
                projection_img.show()
            except RuntimeError as e:
                print("For an output that does not require latex set `show=False`.")
                raise e
        else:
            print(self.explanation.expression)
            self.symbolic_model.print_projections()

    def symbolic_predict(
        self,
        predict_array: np.array,
    ):
        return self.symbolic_model.predict(predict_array)
