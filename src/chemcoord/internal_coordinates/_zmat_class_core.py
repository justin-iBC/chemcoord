# -*- coding: utf-8 -*-
from __future__ import with_statement
from __future__ import division
from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

from chemcoord._exceptions import ERR_CODE_OK, \
    PhysicalMeaning, \
    InvalidReference, ERR_CODE_InvalidReference
from chemcoord._generic_classes._common_class import _common_class
import chemcoord.internal_coordinates._safe_indexers as safe_indexers
from chemcoord.utilities.algebra_utilities import \
    _jit_normalize, \
    _jit_rotation_matrix, \
    _jit_isclose, \
    _jit_cross
from numba import jit
import numpy as np
import pandas as pd
import sympy
import warnings


@jit(nopython=True)
def _jit_calculate_single_position(references, zmat_values, row):
    bond, angle, dihedral = zmat_values[row]
    vb, va, vd = references[0], references[1], references[2]
    zeros = np.zeros(3)
    err = ERR_CODE_OK

    BA = va - vb
    ba = _jit_normalize(BA)
    if _jit_isclose(angle, np.pi):
        d = bond * -ba
    elif _jit_isclose(angle, 0.):
        d = bond * ba
    else:
        AD = vd - va
        N1 = _jit_cross(BA, AD)
        if _jit_isclose(N1, zeros).all():
            err = ERR_CODE_InvalidReference
            d = zeros
        else:
            n1 = _jit_normalize(N1)
            d = bond * ba
            d = np.dot(_jit_rotation_matrix(n1, angle), d)
            d = np.dot(_jit_rotation_matrix(ba, dihedral), d)

    return (err, vb + d)


@jit(nopython=True)
def _jit_give_reference_absolute_position(j):
    # Because dicts are not supported in numba :(
    maxsize = 2**63 - 1
    if j == -maxsize - 1:
        return np.array([0., 0., 0.])
    elif j == -maxsize:
        return np.array([1., 0., 0.])
    elif j == -maxsize + 1:
        return np.array([0., 1., 0.])
    elif j == -maxsize + 2:
        return np.array([0., 0., 1.])
    else:
        raise ValueError


@jit(nopython=True)
def _jit_calculate_everything(positions, c_table, zmat_values, start_row=0):
    for row in range(start_row, c_table.shape[0]):
        ref_pos = np.empty((3, 3))
        threshhold = -2**63 + 100
        for k in range(3):
            j = c_table[row, k]
            if j < threshhold:
                ref_pos[k] = _jit_give_reference_absolute_position(j)
            else:
                ref_pos[k] = positions[j]
        err, pos = _jit_calculate_single_position(ref_pos, zmat_values, row)
        if err == ERR_CODE_OK:
            positions[row] = pos
        elif err == ERR_CODE_InvalidReference:
            return row
    return row


class Zmat_core(_common_class):
    """The main class for dealing with internal coordinates.
    """
    _required_cols = frozenset({'atom', 'b', 'bond', 'a', 'angle',
                                'd', 'dihedral'})

    # overwrites existing method
    def __init__(self, frame, order_of_definition=None):
        """How to initialize a Zmat instance.

        Args:
            init (pd.DataFrame): A Dataframe with at least the columns
                ``['atom', 'b', 'bond', 'a', 'angle',
                'd', 'dihedral']``.
                Where ``'atom'`` is a string for the elementsymbol.
            order_of_definition (list like): Specify in which order
                the Zmatrix is defined. If ``None`` it just uses
                ``self.index``.

        Returns:
            Zmat: A new zmat instance.
        """
        if not isinstance(frame, pd.DataFrame):
            raise ValueError('Need a pd.DataFrame as input')
        if not self._required_cols <= set(frame.columns):
            raise PhysicalMeaning('There are columns missing for a '
                                  'meaningful description of a molecule')
        self._frame = frame.copy()
        self.metadata = {}
        self._metadata = {}
        if order_of_definition is None:
            self._metadata['order'] = self.index
        else:
            self._metadata['order'] = order_of_definition

    # overwrites existing method
    def copy(self):
        molecule = self.__class__(self._frame)
        molecule.metadata = self.metadata.copy()
        keys_to_keep = ['abs_refs', 'cartesian', 'order']
        for key in keys_to_keep:
            try:
                molecule._metadata[key] = self._metadata[key].copy()
            except KeyError:
                pass
        return molecule

    # overwrites existing method
    def _repr_html_(self):
        out = self.copy()
        cols = ['b', 'a', 'd']
        representation = {key: out._metadata['abs_refs'][key][1]
                          for key in out._metadata['abs_refs']}

        def f(x):
            if len(x) == 1:
                return x[0]
            else:
                return x

        for row, i in enumerate(out._metadata['order'][:3]):
            new = f([representation[x] for x in out.loc[i, cols[row:]]])
            out.loc[i, cols[row:]] = new

        def formatter(x):
            if (isinstance(x, sympy.Basic)):
                return '${}$'.format(sympy.latex(x))
            else:
                return x

        out = out.applymap(formatter)

        def insert_before_substring(insert_txt, substr, txt):
            """Under the assumption that substr only appears once.
            """
            return (insert_txt + substr).join(txt.split(substr))
        html_txt = out._frame._repr_html_()
        insert_txt = '<caption>{}</caption>\n'.format(self.__class__.__name__)
        return insert_before_substring(insert_txt, '<thead>', html_txt)

    def _return_appropiate_type(self, selected):
        return selected

    @property
    def safe_loc(self):
        """Label based indexing

        The indexing behaves like
        `Indexing and Selecting data in Pandas <http://pandas.pydata.org/pandas-docs/stable/indexing.html>`_
        The only question is about the return type.
        If the information in the columns is enough to draw a molecule,
        an instance of the own class (e.g. :class:`~chemcoord.Cartesian`)
        is returned.
        If the information in the columns is not enough to draw a molecule
        a :class:`~pandas.Series` instance is returned for one dimensional
        slices and a :class:`~pandas.DataFrame` instance in all other cases.

        Cartesian:
            In the case of a :class:`~chemcoord.Cartesian` class this means:

                ``molecule.loc[:, ['atom', 'x', 'y', 'z']]`` returns a
                :class:`~chemcoord.Cartesian`.

                ``molecule.loc[:, ['atom', 'x']]`` returns a
                :class:`~pandas.DataFrame`.

                ``molecule.loc[:, 'atom']`` returns a
                :class:`~pandas.Series`.

        Zmat:
            If the following definition is used::

                cols = ['atom', 'b', 'bond', 'a', 'angle',
                        'd', 'dihedral']

            The return types in the case of a :class:`~chemcoord.Zmat`
            instance are:

                ``molecule.loc[:, cols]`` returns a :class:`~chemcoord.Zmat`.

                ``molecule.loc[:, ['atom', 'b']]`` returns a
                :class:`~pandas.DataFrame`.

                ``molecule.loc[:, 'atom']`` returns a
                :class:`~pandas.Series`.
        """
        return safe_indexers._Safe_Loc(self)


    @property
    def safe_iloc(self):
        """Label based indexing

        The indexing behaves like
        `Indexing and Selecting data in Pandas <http://pandas.pydata.org/pandas-docs/stable/indexing.html>`_
        The only question is about the return type.
        If the information in the columns is enough to draw a molecule,
        an instance of the own class (e.g. :class:`~chemcoord.Cartesian`)
        is returned.
        If the information in the columns is not enough to draw a molecule
        a :class:`~pandas.Series` instance is returned for one dimensional
        slices and a :class:`~pandas.DataFrame` instance in all other cases.

        Cartesian:
            In the case of a :class:`~chemcoord.Cartesian` class this means:

                ``molecule.loc[:, ['atom', 'x', 'y', 'z']]`` returns a
                :class:`~chemcoord.Cartesian`.

                ``molecule.loc[:, ['atom', 'x']]`` returns a
                :class:`~pandas.DataFrame`.

                ``molecule.loc[:, 'atom']`` returns a
                :class:`~pandas.Series`.

        Zmat:
            If the following definition is used::

                cols = ['atom', 'b', 'bond', 'a', 'angle',
                        'd', 'dihedral']

            The return types in the case of a :class:`~chemcoord.Zmat`
            instance are:

                ``molecule.loc[:, cols]`` returns a :class:`~chemcoord.Zmat`.

                ``molecule.loc[:, ['atom', 'b']]`` returns a
                :class:`~pandas.DataFrame`.

                ``molecule.loc[:, 'atom']`` returns a
                :class:`~pandas.Series`.
        """
        return safe_indexers._Safe_ILoc(self)

    def _test_if_can_be_added(self, other):
        cols = ['atom', 'b', 'a', 'd']
        if not isinstance(other, Zmat_core):
            raise PhysicalMeaning('You can only add zmatrices with each other')
        if not (np.alltrue(self.loc[:, cols] == other.loc[:, cols])
                and np.alltrue(self.index == other.index)):
            message = ("You can add only those zmatrices that have the same "
                       "index, use the same construction table, have the same "
                       "ordering... The only allowed difference is in the "
                       "columns ['bond', 'angle', 'dihedral']")
            raise PhysicalMeaning(message)

    def __add__(self, other):
        self._test_if_can_be_added(other)
        coords = ['bond', 'angle', 'dihedral']
        new = self.copy()
        new.loc[:, coords] = self.loc[:, coords] + other.loc[:, coords]
        return new

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        self._test_if_can_be_added(other)
        coords = ['bond', 'angle', 'dihedral']
        new = self.copy()
        new.loc[:, coords] = self.loc[:, coords] - other.loc[:, coords]
        return new

    def __rsub__(self, other):
        self._test_if_can_be_added(other)
        coords = ['bond', 'angle', 'dihedral']
        new = self.copy()
        new.loc[:, coords] = other.loc[:, coords] - self.loc[:, coords]
        return new

    def __mul__(self, other):
        coords = ['bond', 'angle', 'dihedral']
        new = self.copy()
        new.loc[:, coords] = self.loc[:, coords] * other
        return new

    def __rmul__(self, other):
        coords = ['bond', 'angle', 'dihedral']
        new = self.copy()
        new.loc[:, coords] = self.loc[:, coords] * other
        return new

    def __abs__(self):
        coords = ['bond', 'angle', 'dihedral']
        new = self.copy()
        new.loc[:, coords] = abs(new.loc[:, coords])
        return new

    def __neg__(self):
        return -1 * self.copy()

    def subs(self, variable, value):
        cols = ['bond', 'angle', 'dihedral']
        out = self.copy()

        def give_subs_function(variable, value):
            def subs_function(x):
                try:
                    new = x.subs(variable, value)
                except AttributeError:
                    new = x

                sympy_numbers = (sympy.numbers.Float, sympy.numbers.Integer)
                if isinstance(new, sympy_numbers):
                    return float(new)
                else:
                    return new
            return subs_function

        for col in cols:
            if out[col].dtype is np.dtype('O'):
                series = out[col]
                out[col] = series.map(give_subs_function(variable, value))
                try:
                    out[col] = out[col].astype('float')
                except TypeError:
                    pass
        return out

    def _to_Zmat(self):
        return self.copy()

    def change_numbering(self, new_index=None, inplace=False):
        """Change numbering to a new index.

        Changes the numbering of index and all dependent numbering
            (bond_with...) to a new_index.
        The user has to make sure that the new_index consists of distinct
            elements.

        Args:
            new_index (list): If None the new_index is taken from 1 to the
            number of atoms.

        Returns:
            Zmat: Reindexed version of the zmatrix.
        """
        out = self if inplace else self.copy()

        if (new_index is None):
            new_index = range(len(self))
        elif len(new_index) != len(self):
            raise ValueError('len(new_index) has to be the same as len(self)')

        cols = ['b', 'a', 'd']
        out.loc[:, cols] = out.loc[:, cols].replace(out.index, new_index)
        out.index = new_index
        if not inplace:
            return out

    def has_same_sumformula(self, other):
        same_atoms = True
        for atom in set(self.loc[:, 'atom']):
            own_atom_number = len(self[self['atom'] == atom])
            other_atom_number = len(other[other['atom'] == atom])
            same_atoms = (own_atom_number == other_atom_number)
            if not same_atoms:
                break
        return same_atoms

    def _test_give_cartesian(self):
        abs_refs = self._metadata['abs_refs']
        old_index = self.index
        rename = dict(enumerate(old_index))
        self.change_numbering(inplace=True)
        c_table = self.loc[:, ['b', 'a', 'd']].values
        zmat_values = self.loc[:, ['bond', 'angle', 'dihedral']].values
        zmat_values[:, [1, 2]] = np.radians(zmat_values[:, [1, 2]])
        positions = np.empty((len(self), 3), dtype='float64')

        row = _jit_calculate_everything(positions, c_table, zmat_values)
        if row < len(self) - 1:
            i = rename[row]
            self.change_numbering(old_index, inplace=True)
            b, a, d = self.loc[i, ['b', 'a', 'd']]
            raise InvalidReference(i=i, b=b, a=a, d=d)
        return positions

    def insert_dummy(self, i, references):
        """Insert dummy atom into ``self``

        ``i`` uses introduced dummy atom as reference (instead of ``d``)
        """
        coords = ['x', 'y', 'z']
        cols = ['b', 'a', 'd']
        i_dummy = max(self.index) + 1

        def insert_row(df, pos, key):
            if pos < len(df):
                middle = df.iloc[pos:(pos + 1)]
                middle.index = [key]
                start, end = df.iloc[:pos], df.iloc[pos:]
                return pd.concat([start, middle, end])
            elif pos == len(df):
                start = df.copy()
                start.loc[key] = start.iloc[-1]
                return start

        zframe = insert_row(self._frame.copy(), self.index.get_loc(i), i_dummy)
        zframe.loc[i_dummy, 'atom'] = 'X'
        zframe.loc[i_dummy, cols] = zframe.loc[references['d'], cols]

        def get_dummy_cart_pos(xyz, reference_labels):
            b_pos, a_pos, d_pos = xyz._give_location(reference_labels)
            BA = a_pos - b_pos
            AD = d_pos - a_pos
            N1 = np.cross(BA, AD)
            n1 = N1 / np.linalg.norm(N1)
            N2 = np.cross(N1, BA)
            n2 = N2 / np.linalg.norm(N2)
            return a_pos + n2

        xyz = self._metadata['cartesian']
        dummy_pos = get_dummy_cart_pos(xyz, zframe.loc[i, cols])
        xyz.loc[i_dummy, 'atom'] = 'X'
        xyz.loc[i_dummy, ['x', 'y', 'z']] = dummy_pos
        return xyz

        def get_zmat_values(positions):
            IB = positions[1] - positions[0]
            BA = positions[2] - positions[1]
            AD = positions[3] - positions[2]

            bond = np.linalg.norm(IB, axis=1)

            ba = BA / np.linalg.norm(BA, axis=1)[:, None]
            bi = -1 * IB / np.linalg.norm(IB, axis=1)[:, None]
            dot_product = np.sum(bi * ba, axis=1)
            dot_product[dot_product > 1] = 1
            dot_product[dot_product < -1] = -1

            N1 = np.cross(IB, BA, axis=1)
            N2 = np.cross(BA, AD, axis=1)
            n1, n2 = [v / np.linalg.norm(v, axis=1)[:, None] for v in (N1, N2)]
            dot_product = np.sum(n1 * n2, axis=1)
            dot_product[dot_product > 1] = 1
            dot_product[dot_product < -1] = -1
            dihedrals = np.degrees(np.arccos(dot_product))
            # the next lines are to test the direction of rotation.
            # is a dihedral really 90 or 270 degrees?
            # Equivalent to direction of rotation of dihedral
            where_to_modify = np.sum(BA * np.cross(n1, n2, axis=1), axis=1) > 0
            where_to_modify = np.nonzero(where_to_modify)[0]
            sign = np.full_like(dihedrals, 1)
            to_add = np.full_like(dihedrals, 0)
            sign[where_to_modify] = -1
            to_add[where_to_modify] = 360
            return bond, angle, dihedral

        zframe.loc[i, 'd'] = i_dummy


        # [dummy_pos] + xyz._give_location(zframe.loc[i_dummy, cols])
        # get_zmat_values

        # calculate values for i and 'X'


        # modify zframe

        # return self.__class__(zframe)
        return zmolecule

    def give_cartesian(self):
        abs_refs = self._metadata['abs_refs']
        old_index = self.index
        rename = dict(enumerate(old_index))
        self.change_numbering(inplace=True)
        c_table = self.loc[:, ['b', 'a', 'd']].values
        zmat_values = self.loc[:, ['bond', 'angle', 'dihedral']].values
        zmat_values[:, [1, 2]] = np.radians(zmat_values[:, [1, 2]])
        positions = np.empty((len(self), 3), dtype='float64')

        row = _jit_calculate_everything(positions, c_table, zmat_values)
        if row < len(self) - 1:
            print('Error handling required', rename[row])

        xyz_frame = pd.DataFrame(columns=['atom', 'x', 'y', 'z'], dtype=float)
        xyz_frame['atom'] = self['atom']
        xyz_frame.loc[:, ['x', 'y', 'z']] = positions

        self.change_numbering(old_index, inplace=True)
        xyz_frame.index = self.index
        from chemcoord.cartesian_coordinates.cartesian_class_main \
            import Cartesian
        return Cartesian(xyz_frame)

    def to_xyz(self, *args, **kwargs):
        """Deprecated, use :meth:`~chemcoord.Zmat.give_cartesian`
        """
        message = 'Will be removed in the future. Please use give_cartesian.'
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.warn(message, DeprecationWarning)
        return self.give_cartesian(*args, **kwargs)
