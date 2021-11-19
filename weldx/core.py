"""Collection of common classes and functions."""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Dict, List, Tuple, Union
from warnings import warn

import numpy as np
import pandas as pd
import pint
import xarray
import xarray as xr

import weldx.util as ut
from weldx.constants import Q_, U_
from weldx.time import Time, TimeDependent, types_time_like

if TYPE_CHECKING:
    import matplotlib.pyplot
    import sympy

__all__ = ["GenericSeries", "MathematicalExpression", "TimeSeries"]


_me_parameter_types = Union[pint.Quantity, str, Tuple[pint.Quantity, str], xr.DataArray]


class MathematicalExpression:
    """Mathematical expression using sympy syntax."""

    def __init__(
        self,
        expression: Union[sympy.Expr, str],
        parameters: _me_parameter_types = None,
    ):
        """Construct a MathematicalExpression.

        Parameters
        ----------
        expression
            A sympy expression or a string that can be evaluated as one.
        parameters :
            A dictionary containing constant values for variables of the
            expression.

        """
        import sympy

        if not isinstance(expression, sympy.Expr):
            expression = sympy.sympify(expression)
        self._expression = expression

        self.function = sympy.lambdify(
            tuple(self._expression.free_symbols), self._expression, "numpy"
        )

        self._parameters: Union[pint.Quantity, xr.DataArray] = {}
        if parameters is not None:
            self.set_parameters(parameters)

    def __repr__(self):
        """Give __repr__ output."""
        representation = (
            f"<MathematicalExpression>\n"
            f"Expression:\n\t {self._expression.__repr__()}"
            f"\nParameters:\n"
        )
        if len(self._parameters) > 0:
            for parameter, value in self._parameters.items():
                representation += f"\t{parameter} = {value}\n"
        else:
            representation += "\tNone"
        return representation

    def __eq__(self, other):
        """Return the result of a structural equality comparison with another object.

        If the other object is not a 'MathematicalExpression' this function always
        returns 'False'.

        Parameters
        ----------
        other:
            Other object.

        Returns
        -------
        bool:
            'True' if the compared object is also a 'MathematicalExpression' and equal
            to this instance, 'False' otherwise

        """
        return self.equals(other, check_parameters=True, check_structural_equality=True)

    def equals(
        self,
        other: Any,
        check_parameters: bool = True,
        check_structural_equality: bool = False,
    ):
        """Compare the instance with another object for equality and return the result.

        If the other object is not a MathematicalExpression this function always returns
        'False'. The function offers the choice to compare for structural or
        mathematical equality by setting the 'structural_expression_equality' parameter
        accordingly. Additionally, the comparison can be limited to the expression only,
        if 'check_parameters' is set to 'False'.

        Parameters
        ----------
        other:
            Arbitrary other object.
        check_parameters
            Set to 'True' if the parameters should be included during the comparison. If
            'False', only the expression is checked for equality.
        check_structural_equality:
            Set to 'True' if the expression should be checked for structural equality.
            Set to 'False' if mathematical equality is sufficient.

        Returns
        -------
        bool:
            'True' if both objects are equal, 'False' otherwise

        """
        if isinstance(other, MathematicalExpression):
            if check_structural_equality:
                equality = self.expression == other.expression
            else:
                from sympy import simplify

                equality = simplify(self.expression - other.expression) == 0

            if check_parameters:
                from weldx.util import compare_nested

                equality = equality and compare_nested(
                    self._parameters, other.parameters
                )
            return equality
        return False

    def set_parameter(self, name, value):
        """Define an expression parameter as constant value.

        Parameters
        ----------
        name
            Name of the parameter used in the expression.
        value
            Parameter value. This can be number, array or pint.Quantity

        """
        self.set_parameters({name: value})

    # todo: Use kwargs here???
    def set_parameters(self, params: _me_parameter_types):
        """Set the expressions parameters.

        Parameters
        ----------
        params:
            Dictionary that contains the values for the specified parameters.

        """
        if not isinstance(params, dict):
            raise ValueError(f'"parameters" must be dictionary, got {type(params)}')

        variable_names = [str(v) for v in self._expression.free_symbols]

        for k, v in params.items():
            if k not in variable_names:
                raise ValueError(f'The expression does not have a parameter "{k}"')
            if isinstance(v, tuple):
                v = xr.DataArray(v[0], dims=v[1])
            if not isinstance(v, xr.DataArray):
                v = Q_(v)
            self._parameters[k] = v

    @property
    def num_parameters(self):
        """Get the expressions number of parameters.

        Returns
        -------
        int:
            Number of parameters.

        """
        return len(self._parameters)

    @property
    def num_variables(self):
        """Get the expressions number of free variables.

        Returns
        -------
        int:
            Number of free variables.

        """
        return len(self.expression.free_symbols) - len(self._parameters)

    @property
    def expression(self):
        """Return the internal sympy expression.

        Returns
        -------
        sympy.core.expr.Expr:
            Internal sympy expression

        """
        return self._expression

    @property
    def parameters(self) -> Dict:
        """Return the internal parameters dictionary.

        Returns
        -------
        Dict
            Internal parameters dictionary

        """
        return self._parameters

    def get_variable_names(self) -> List:
        """Get a list of all expression variables.

        Returns
        -------
        List:
            List of all expression variables

        """
        return [
            str(var)
            for var in self._expression.free_symbols
            if str(var) not in self._parameters
        ]

    def evaluate(self, **kwargs) -> Any:
        """Evaluate the expression for specific variable values.

        Parameters
        ----------
        kwargs
            additional keyword arguments (variable assignment) to pass.

        Returns
        -------
        Any:
            Result of the evaluated function

        """
        intersection = set(kwargs).intersection(self._parameters)
        if len(intersection) > 0:
            raise ValueError(
                f"The variables {intersection} are already defined as parameters."
            )

        variables = {
            k: v if isinstance(v, xr.DataArray) else xr.DataArray(Q_(v))
            for k, v in kwargs.items()
        }

        parameters = {
            k: v if isinstance(v, xr.DataArray) else xr.DataArray(v)
            for k, v in self._parameters.items()
        }

        return self.function(**variables, **parameters)


# TimeSeries ---------------------------------------------------------------------------


class TimeSeries(TimeDependent):
    """Describes the behaviour of a quantity in time."""

    _valid_interpolations = [
        "step",
        "linear",
        "nearest",
        "zero",
        "slinear",
        "quadratic",
        "cubic",
    ]

    def __init__(
        self,
        data: Union[pint.Quantity, MathematicalExpression],
        time: types_time_like = None,
        interpolation: str = None,
        reference_time: pd.Timestamp = None,
    ):
        """Construct a TimSeries.

        Parameters
        ----------
        data:
            Either a pint.Quantity or a weldx.MathematicalExpression. If a mathematical
            expression is chosen, it is only allowed to have a single free variable,
            which represents time.
        time:
            An instance of pandas.TimedeltaIndex if a quantity is passed and 'None'
            otherwise.
        interpolation:
            A string defining the desired interpolation method. This is only relevant if
            a quantity is passed as data. Currently supported interpolation methods are:
            'step', 'linear'.

        """
        self._data: Union[MathematicalExpression, xr.DataArray] = None
        self._time_var_name = None  # type: str
        self._shape = None
        self._units = None
        self._interp_counter = 0
        self._reference_time = reference_time

        if isinstance(data, (pint.Quantity, xr.DataArray)):
            self._initialize_discrete(data, time, interpolation)
        elif isinstance(data, MathematicalExpression):
            self._init_expression(data)
        else:
            raise TypeError(f'The data type "{type(data)}" is not supported.')

    def __eq__(self, other: Any) -> bool:
        """Return the result of a structural equality comparison with another object.

        If the other object is not a 'TimeSeries' this function always returns 'False'.

        Parameters
        ----------
        other:
            Other object.

        Returns
        -------
        bool:
           'True' if the compared object is also a 'TimeSeries' and equal to
            this instance, 'False' otherwise

        """
        if not isinstance(other, TimeSeries):
            return False
        if not isinstance(self.data, MathematicalExpression):
            if not isinstance(other.data, pint.Quantity):
                return False
            return self._data.identical(other.data_array)  # type: ignore

        return self._data == other.data

    def __repr__(self):
        """Give __repr__ output."""
        representation = "<TimeSeries>"
        if isinstance(self._data, xr.DataArray):
            if self._data.shape[0] == 1:
                representation += f"\nConstant value:\n\t{self.data.magnitude[0]}\n"
            else:
                representation += (
                    f"\nTime:\n\t{self.time}\n"
                    f"Values:\n\t{self.data.magnitude}\n"
                    f'Interpolation:\n\t{self._data.attrs["interpolation"]}\n'
                )
        else:
            representation += self.data.__repr__().replace(
                "<MathematicalExpression>", ""
            )
        return representation + f"Units:\n\t{self.units}\n"

    @staticmethod
    def _check_data_array(data_array: xr.DataArray):
        """Raise an exception if the 'DataArray' can't be used as 'self._data'."""
        try:
            ut.xr_check_coords(data_array, dict(time={"dtype": ["timedelta64[ns]"]}))
        except (KeyError, TypeError, ValueError) as e:
            raise type(e)(
                "The provided 'DataArray' does not match the required pattern. It "
                "needs to have a dimension called 'time' with coordinates of type "
                "'timedelta64[ns]'. The error reported by the comparison function was:"
                f"\n{e}"
            )

        if not isinstance(data_array.data, pint.Quantity):
            raise TypeError("The data of the 'DataArray' must be a 'pint.Quantity'.")

    @staticmethod
    def _create_data_array(
        data: Union[pint.Quantity, xr.DataArray], time: Time
    ) -> xr.DataArray:
        if isinstance(data, xr.DataArray):
            return data
        return (
            xr.DataArray(data=data)
            .rename({"dim_0": "time"})
            .assign_coords({"time": time.as_timedelta_index()})
        )

    def _initialize_discrete(
        self,
        data: Union[pint.Quantity, xr.DataArray],
        time: types_time_like = None,
        interpolation: str = None,
    ):
        """Initialize the internal data with discrete values."""
        # set default interpolation
        if interpolation is None:
            interpolation = "step"

        if isinstance(data, xr.DataArray):
            self._check_data_array(data)
            data = data.transpose("time", ...)
            self._data = data
            # todo: set _reference_time?
        else:
            # expand dim for scalar input
            data = Q_(data)
            if not np.iterable(data):
                data = np.expand_dims(data, 0)

            # constant value case
            if time is None:
                time = pd.Timedelta(0)
            time = Time(time)

            self._reference_time = time.reference_time
            self._data = self._create_data_array(data, time)
        self.interpolation = interpolation

    def _init_expression(self, data):
        """Initialize the internal data with a mathematical expression."""
        if data.num_variables != 1:
            raise Exception(
                "The mathematical expression must have exactly 1 free "
                "variable that represents time."
            )

        # check that the expression can be evaluated with a time quantity
        time_var_name = data.get_variable_names()[0]
        try:
            eval_data = data.evaluate(**{time_var_name: Q_(1, "second")}).data
            self._units = eval_data.units
            if np.iterable(eval_data):
                self._shape = eval_data.shape
            else:
                self._shape = (1,)
        except pint.errors.DimensionalityError:
            raise Exception(
                "Expression can not be evaluated with "
                '"weldx.Quantity(1, "seconds")"'
                ". Ensure that every parameter posses the correct unit."
            )

        # assign internal variables
        self._data = data
        self._time_var_name = time_var_name

        # check that all parameters of the expression support time arrays
        try:
            self.interp_time(Q_([1, 2], "second"))
            self.interp_time(Q_([1, 2, 3], "second"))
        except Exception as e:
            raise Exception(
                "The expression can not be evaluated with arrays of time deltas. "
                "Ensure that all parameters that are multiplied with the time "
                "variable have an outer dimension of size 1. This dimension is "
                "broadcasted during multiplication. The original error message was:"
                f' "{str(e)}"'
            )

    def _interp_time_discrete(self, time: Time) -> xr.DataArray:
        """Interpolate the time series if its data is composed of discrete values."""
        return ut.xr_interp_like(
            self._data,
            {"time": time.as_data_array()},
            method=self.interpolation,
            assume_sorted=False,
            broadcast_missing=False,
        )

    def _interp_time_expression(self, time: Time, time_unit: str) -> xr.DataArray:
        """Interpolate the time series if its data is a mathematical expression."""
        time_q = time.as_quantity(unit=time_unit)
        if len(time_q.shape) == 0:
            time_q = np.expand_dims(time_q, 0)

        time_xr = xr.DataArray(time_q, dims=["time"])

        # evaluate expression
        data = self._data.evaluate(**{self._time_var_name: time_xr})
        return data.assign_coords({"time": time.as_data_array()})

    @property
    def data(self) -> Union[pint.Quantity, MathematicalExpression]:
        """Return the data of the TimeSeries.

        This is either a set of discrete values/quantities or a mathematical expression.

        Returns
        -------
        pint.Quantity:
            Underlying data array.
        MathematicalExpression:
            A mathematical expression describing the time dependency

        """
        if isinstance(self._data, xr.DataArray):
            return self._data.data
        return self._data

    @property
    def data_array(self) -> Union[xr.DataArray, None]:
        """Return the internal data as 'xarray.DataArray'.

        If the TimeSeries contains an expression, 'None' is returned.

        Returns
        -------
        xarray.DataArray:
            The internal data as 'xarray.DataArray'

        """
        if isinstance(self._data, xr.DataArray):
            return self._data
        return None

    @property
    def interpolation(self) -> Union[str, None]:
        """Return the interpolation.

        Returns
        -------
        str:
            Interpolation of the TimeSeries

        """
        if isinstance(self._data, xr.DataArray):
            return self._data.attrs["interpolation"]
        return None

    @interpolation.setter
    def interpolation(self, interpolation):
        if isinstance(self._data, xr.DataArray):
            if interpolation not in self._valid_interpolations:
                raise ValueError(
                    "A valid interpolation method must be specified if discrete "
                    f'values are used. "{interpolation}" is not supported'
                )
            if self.time is None and interpolation != "step":
                interpolation = "step"
            self.data_array.attrs["interpolation"] = interpolation

    @property
    def is_discrete(self) -> bool:
        """Return `True` if the time series is described by discrete values."""
        return not self.is_expression

    @property
    def is_expression(self) -> bool:
        """Return `True` if the time series is described by an expression."""
        return isinstance(self.data, MathematicalExpression)

    @property
    def time(self) -> Union[None, Time]:
        """Return the data's timestamps.

        Returns
        -------
        pandas.TimedeltaIndex:
            Timestamps of the  data

        """
        if isinstance(self._data, xr.DataArray) and len(self._data.time) > 1:
            return Time(self._data.time.data, self.reference_time)
        return None

    @property
    def reference_time(self) -> Union[pd.Timestamp, None]:
        """Get the reference time."""
        return self._reference_time

    def interp_time(
        self, time: Union[pd.TimedeltaIndex, pint.Quantity, Time], time_unit: str = "s"
    ) -> TimeSeries:
        """Interpolate the TimeSeries in time.

        If the internal data consists of discrete values, an interpolation with the
        prescribed interpolation method is performed. In case of mathematical
        expression, the expression is evaluated for the given timestamps.

        Parameters
        ----------
        time:
            The time values to be used for interpolation.
        time_unit:
            Only important if the time series is described by an expression and a
            'pandas.TimedeltaIndex' is passed to this function. In this case, time is
            converted to a quantity with the provided unit. Even though pint handles
            unit prefixes automatically, the accuracy of the results can be heavily
            influenced if the provided unit results in extreme large or
            small values when compared to the parameters of the expression.

        Returns
        -------
        TimeSeries :
            A new `TimeSeries` object containing the interpolated data.

        """
        if self._interp_counter > 0:
            warn(
                "The data of the time series has already been interpolated "
                f"{self._interp_counter} time(s)."
            )

        # prepare timedelta values for internal interpolation
        time = Time(time)
        time_interp = Time(time, self.reference_time)

        if isinstance(self._data, xr.DataArray):
            dax = self._interp_time_discrete(time_interp)
            ts = TimeSeries(data=dax.data, time=time, interpolation=self.interpolation)
        else:
            dax = self._interp_time_expression(time_interp, time_unit)
            ts = TimeSeries(data=dax, interpolation=self.interpolation)

        ts._interp_counter = self._interp_counter + 1
        return ts

    def plot(
        self,
        time: Union[pd.TimedeltaIndex, pint.Quantity] = None,
        axes: matplotlib.pyplot.Axes = None,
        data_name: str = "values",
        time_unit: Union[str, pint.Unit] = None,
        **mpl_kwargs,
    ) -> matplotlib.pyplot.Axes:
        """Plot the `TimeSeries`.

        Parameters
        ----------
        time :
            The points in time that should be plotted. This is an optional parameter for
            discrete `TimeSeries` but mandatory for expression based TimeSeries.
        axes :
            An optional matplotlib axes object
        data_name :
            Name of the data that will appear in the y-axis label
        mpl_kwargs :
            Key word arguments that are passed to the matplotlib plot function
        time_unit :
            The desired time unit for the plot. If `None` is provided, the internally
            stored unit will be used.

        Returns
        -------
        matplotlib.axes._axes.Axes :
            The matplotlib axes object that was used for the plot

        """
        import matplotlib.pyplot as plt

        if axes is None:
            _, axes = plt.subplots()
        if self.is_expression or time is not None:
            return self.interp_time(time).plot(
                axes=axes, data_name=data_name, time_unit=time_unit, **mpl_kwargs
            )

        time = Time(self.time, self.reference_time).as_quantity()
        if time_unit is not None:
            time = time.to(time_unit)

        axes.plot(time.m, self._data.data.m, **mpl_kwargs)  # type: ignore
        axes.set_xlabel(f"t in {time.u:~}")
        y_unit_label = ""
        if self.units not in ["", "dimensionless"]:
            y_unit_label = f" in {self.units:~}"
        axes.set_ylabel(data_name + y_unit_label)

        return axes

    @property
    def shape(self) -> Tuple:
        """Return the shape of the TimeSeries data.

        For mathematical expressions, the shape does not contain the time axis.

        Returns
        -------
        Tuple:
            Tuple describing the data's shape

        """
        if isinstance(self._data, xr.DataArray):
            return self._data.shape
        return self._shape

    @property
    def units(self) -> pint.Unit:
        """Return the units of the TimeSeries Data.

        Returns
        -------
        pint.Unit:
            The unit of the `TimeSeries`

        """
        if isinstance(self._data, xr.DataArray):
            return self._data.data.units
        return self._units


# GenericSeries ------------------------------------------------------------------------


class GenericSeries:
    """Describes a quantity depending on one or more parameters."""

    _allowed_variables: List[str] = None
    """Allowed variable names"""
    _required_variables: List[str] = None
    """Required variable names"""

    _evaluation_preprocessor: callable = None
    """Function that should be used to adjust a var. input - (f.e. convert to Time)"""

    _required_dimensions: List[str] = None
    """Required dimensions"""

    _required_unit_dimensionality: pint.Unit = None
    """Required unit dimensionality of the evaluated expression/data"""

    # do it later
    # needs pint-xarray for a good implementation
    _expected_dimension_units: Dict[str, pint.Unit] = None
    """Expected units of a dimension"""
    _required_parameter_coordinates: Dict[str, List] = None
    """For xarray assign_coords"""

    _required_parameter_shape: Dict[str, int] = None
    """Size of the parameter dimensions/coordinates - (also defines parameter order)"""
    _alias_names: Dict[str, List[str]] = None
    """Allowed alias names for a variable or parameter in an expression"""

    # todo: other possible constraints:
    # - allowed dimensions (not the same as allowed variables)

    @classmethod
    def _check_constraints(cls, dims, units_out: pint.Unit = None):
        if cls._required_dimensions is not None:
            for v in cls._required_dimensions:
                if v not in dims:
                    raise ValueError(f"{cls.__name__} requires dimension '{v}'.")
        if cls._required_unit_dimensionality is not None:
            if not units_out.dimensionality == cls._required_unit_dimensionality:
                raise ValueError(
                    f"{cls.__name__} requires its output unit to be of dimensionality "
                    f"'{cls._required_unit_dimensionality}' but it actually is "
                    f"'{units_out.dimensionality}'."
                )

    @classmethod
    def _check_constraints_discrete(cls, data_array: xr.DataArray):
        if cls is GenericSeries:
            return

        cls._check_constraints(data_array.dims, data_array.data.u)

    @classmethod
    def _check_constraints_expression(
        cls,
        expr: MathematicalExpression,
        var_dims: Dict[str, str],
        expr_units: pint.Unit,
    ):
        if cls is GenericSeries:
            return

        if cls._allowed_variables is not None:
            for v in expr.get_variable_names():
                if v not in cls._allowed_variables:
                    raise ValueError(
                        f"'{v}' is not allowed as an expression variable of class "
                        f"{cls.__name__}"
                    )
        if cls._required_variables is not None:
            for v in cls._required_variables:
                if v not in expr.get_variable_names():
                    raise ValueError(
                        f"{cls.__name__} requires expression variable '{v}'."
                    )

        dims = cls._get_expression_dims(expr, var_dims)
        cls._check_constraints(dims, expr_units)

    # todo: add limits for dims?

    def __init__(
        self,
        data: Union[pint.Quantity, xr.DataArray, MathematicalExpression],
        dims: Union[List[str], Dict[str, Union[str, pint.Unit]]] = None,
        coords: Union[None, pint.Quantity, Dict[str, pint.Quantity]] = None,
        units: Dict[str, Union[str, pint.Unit]] = None,
        interpolation: str = None,
        parameters: Dict[str, Union[str, pint.Quantity]] = None,
    ):
        """Create a generic series.

        Parameters
        ----------
        data :
            Either a multidimensional array of discrete values or a
            `MathematicalExpression` with one or more variables.
        dims :
            The names of the dimensions. The order must be adjusted to the data's shape
            (outer dimensions first). For mathematical expressions, the dimensions
            match the variable names and need not to be specified.
        coords :
            The coordinate values in case the data is a set of discrete values.
        interpolation :
            The method that should be used when interpolating between discrete values.

        """

        self._data: Union[xr.DataArray, MathematicalExpression] = None
        self._variable_units: Dict[str, pint.Unit] = None
        self._symbol_dims: Dict[str, List[str]] = None
        self._shape: Tuple = None
        self._units: pint.Unit = None
        self._interpolation = "linear"

        if isinstance(data, (pint.Quantity, xr.DataArray)):
            self._init_discrete(data, dims, coords)
        elif isinstance(data, (MathematicalExpression, str)):
            self._init_expression(data, dims, parameters, units)
        else:
            raise TypeError(f'The data type "{type(data)}" is not supported.')

    def _init_discrete(self, data, dims, coords):
        """Initialize the internal data with discrete values."""
        # todo: preserve units of coordinates somehow
        if not isinstance(data, xr.DataArray):
            if coords is not None:
                coords = {
                    k: xr.DataArray(Q_(v), dims=[k]).pint.dequantify()
                    for k, v in coords.items()
                }
            data = xr.DataArray(data=data, dims=dims, coords=coords)
        else:
            # todo check data structure
            pass

        self._check_constraints_discrete(data)

        self._data = data

    def _check_parameters(self, parameters):
        pass

    def _init_expression(self, expr, dims, parameters, units):
        """Initialize the internal data with a mathematical expression."""
        # Check and update expression
        if isinstance(expr, MathematicalExpression):
            parameters = expr.parameters
            expr = expr.expression.__repr__()
        if parameters is not None:
            self._update_expression_params(parameters)
        expr = MathematicalExpression(expr, parameters)

        if expr.num_variables == 0:
            raise ValueError("The passed expression has no variables.")

        # Update units and dims
        if dims is None:
            dims = {}
        if units is None:
            units = {}
        else:
            for k, v in units.items():
                if k not in expr.get_variable_names():
                    raise KeyError(f"{k} is not a variable of the expression:\n{expr}")
                units[k] = U_(v)

        for v in expr.get_variable_names():
            if v not in dims:
                dims[v] = v
            if v not in units:
                units[v] = U_("")

        # check expression
        expr_units, expr_shape = self._eval_expr(expr, dims, units)

        # check constraints
        self._check_constraints_expression(expr, dims, expr_units)

        # save internal data
        self._units = expr_units
        self._shape = expr_shape
        self._data = expr
        self._variable_units = units
        self._symbol_dims = dims

    @staticmethod
    def _eval_expr(expr, dims, units):
        try:
            scalar_params = {k: Q_(1, v) for k, v in units.items()}
            result = expr.evaluate(**scalar_params)
            expr_units = result.data.to_reduced_units().units
        except pint.errors.DimensionalityError as e:
            raise ValueError(
                "Expression can not be evaluated due to a unit dimensionality error. "
                "Ensure that the expressions parameters and the expected variable "
                f"units are compatible. The original exception was:\n{e}"
            )
        except ValueError:
            pass  # Error message will be generated by the next check

        try:
            # we evaluate twice with different array sizes because it might happen that
            # a parameter uses the same dimension as a variable but the check still
            # passes because the test input for the variable has the same array length.
            # This case will be caught in the second evaluation.
            for offset in range(2):
                array_params = {
                    k: xr.DataArray(Q_(range(i + 2 + offset), v), dims=dims[k])
                    for i, (k, v) in enumerate(units.items())
                }
                expr.evaluate(**array_params)
        except ValueError as e:
            raise ValueError(
                "During the evaluation of the expression mismatching array lengths' "
                "were detected. Some possible causes are:\n"
                "  - expression parameters that have already assigned coordinates to a "
                "dimension that is also used as a variable\n"
                "  - 2 free dimensions with identical names\n"
                "  - 2 expression parameters that use the same dimension with "
                "different number of values\n"
                f"The original exception was:\n{e}"
            )

        # todo: shape should follow from dims of parameters and variables - Consider
        #       removing shape for expressions since it does not really make sense. User
        #       alternatives would be ndims and dims

        shape = None
        return expr_units, shape

    @staticmethod
    def _update_expression_params(params):
        for k, v in params.items():
            if isinstance(v, tuple):
                v = (Q_(v[0]), v[1])
            elif isinstance(v, xr.DataArray):
                if not isinstance(v.data, pint.Quantity):
                    raise ValueError(f"Value for parameter {k} is not a quantity.")
            else:
                v = Q_(v)
            params[k] = v

    def __repr__(self):
        """Give __repr__ output."""
        representation = "<GenericSeries>\n"
        if isinstance(self._data, xr.DataArray):
            representation += f"Values:\n{self._data.data.magnitude}\n"
        else:
            representation += self.data.__repr__().replace(
                "<MathematicalExpression>", ""
            )
        representation += f"Dimensions:\n\t{self.dims}\n"
        if isinstance(self._data, xr.DataArray):
            representation += f"Coordinates:\n\t{self.coordinates}\n"
        return representation + f"Units:\n\t{self.units}\n"

    def __add__(self, other):
        # this should mostly be moved to the MathematicalExpression
        # todo:
        #   - for two expressions simply do: f"{exp_1} + f{exp_2}" and merge the
        #     parameters in a new MathExpression
        #   - for two discrete series call __add__ of the xarrays
        #   - for mixed version add a new parameter to the expression string and set the
        #     xarray as the parameters value
        raise NotImplementedError

    def __call__(self, **kwargs) -> GenericSeries:
        """Interpolate the generic series at discrete points.

        Parameters
        ----------

        Returns
        -------
        GenericSeries :
            A new generic series containing the discrete values at the desired
            coordinates.

        """
        if self._evaluation_preprocessor is not None:
            kwargs = self._evaluation_preprocessor(**kwargs)
        input = {}
        for i, (k, v) in enumerate(kwargs.items()):
            v = Q_(v)
            if len(v.shape) == 0:
                v = np.expand_dims(v, 0)
            if isinstance(self._data, MathematicalExpression):
                v = xr.DataArray(
                    v, dims=self._symbol_dims[k], coords={self._symbol_dims[k][0]: v.m}
                )
            else:
                ref_unit = self._data.coords[k].attrs["units"]
                v = xr.DataArray(v.to(ref_unit), dims=[k]).pint.dequantify()
            input[k] = v

        if isinstance(self._data, MathematicalExpression):
            # num_expr_sym = self._data.num_variables + len(self._data.parameters)
            if len(kwargs) == self._data.num_variables:
                data = self._data.evaluate(**input)
                return GenericSeries(data)
            else:
                new_series = deepcopy(self)
                for k, v in kwargs.items():
                    new_series._data.set_parameter(k, (v, self._symbol_dims[k]))
                    new_series._symbol_dims.pop(k)
                    new_series._variable_units.pop(k)
                return new_series

        for k in input.keys():
            if k not in self._data.dims:
                raise KeyError(f"'{k}' is not a valid dimension.")
        return GenericSeries(ut.xr_interp_like(self._data, input))

    def __getitem__(self, *args):
        if isinstance(self._data, xr.DataArray):
            return self._data.__getitem__(*args)
        return NotImplementedError

    def interp_dim(self, dimension: str, coordinates: pint.Quantity) -> GenericSeries:
        """Interpolate only in a single dimension.

        Parameters
        ----------
        dimension :
            The interpolations dimension
        coordinates :
            The coordinates that should be interpolated

        Returns
        -------
        GenericSeries :
            A new generic series containing discrete values for the interpolated
            dimensions.

        """
        raise NotImplementedError

    def interp_like(
        self, obj: Any, dimensions: List[str] = None, accessor_mappings: Dict = None
    ) -> GenericSeries:
        """Interpolate using the coordinates of another object.

        Parameters
        ----------
        obj :
            An object that provides the coordinate values.
        dimensions :
            The dimensions that should be interpolated. If `None` is passed, all
            dimensions will be interpolated
        accessor_mappings :
            A mapping between the dimensions of the generic series and the corresponding
            coordinate accessor of the provided object. This can be used if the
            coordinate names do not match for the time series and the provided object.

        Returns
        -------
        GenericSeries :
            A new generic series containing discrete values for the interpolated
            dimensions.

        """
        raise NotImplementedError

    @property
    def coordinates(self) -> Union[None, pint.Quantity, Dict[str, pint.Quantity]]:
        """Get the coordinates of the generic series."""
        if isinstance(self._data, xr.DataArray):
            return self._data.coords
        return None

    @property
    def coordinate_names(self) -> List[str]:
        """Get the names of all coordinates."""
        raise NotImplementedError

    @property
    def data(self) -> Union[pint.Quantity, MathematicalExpression]:
        """Get the internal data."""
        if isinstance(self._data, xr.DataArray):
            return self._data.data
        return self._data

    @property
    def data_array(self) -> Union[xarray.DataArray, MathematicalExpression]:
        """Get the internal data."""
        if isinstance(self._data, xr.DataArray):
            return self._data
        raise NotImplementedError

    @staticmethod
    def _get_expression_dims(expr: MathematicalExpression, symbol_dims: Dict[str, str]):
        dims = set()
        for d in symbol_dims.values():
            dims |= set(d)
        for v in expr.parameters.values():
            if not isinstance(v, xr.DataArray):
                v = xr.DataArray(v)
            if v.size > 0:
                dims |= set(v.dims)
        return list(dims)

    @property
    def dims(self) -> List[str]:
        """Get the names of all dimensions."""
        if isinstance(self._data, MathematicalExpression):
            return self._get_expression_dims(self._data, self._symbol_dims)
        return self._data.dims

    @property
    def interpolation(self) -> str:
        """Get the name of the used interpolation method."""
        return self._interpolation

    @interpolation.setter
    def interpolation(self, val: str):
        if val not in ["linear", "step"]:
            raise ValueError(f"'{val}' is not a supported interpolation method.")
        self._interpolation = val

    @property
    def ndims(self) -> int:
        """Get the number of dimensions."""
        return len(self.dims)

    @property
    def parameter_names(self) -> List[str]:
        """Get the names of all dimensions."""
        if self._variable_units is not None:
            return list(self._variable_units.keys())
        return None

    @property
    def parameter_units(self) -> Dict[str, pint.Unit]:
        """Get a dictionary that maps the parameter names to their expected units."""
        return self._variable_units

    @property
    def shape(self) -> Tuple:
        """Get the shape of the generic series data."""
        if self._shape is not None:
            return self._shape
        raise NotImplementedError

    @property
    def units(self) -> str:
        """Get the units of the generic series data."""
        if self._units is not None:
            return self._units
        return self._data.data.u
