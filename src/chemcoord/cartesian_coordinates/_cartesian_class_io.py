# -*- coding: utf-8 -*-
from __future__ import with_statement
from __future__ import division
from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

from chemcoord.cartesian_coordinates._cartesian_class_core \
    import CartesianCore
from chemcoord.configuration import settings
from io import open
import numpy as np
import os
import pandas as pd
import subprocess
import tempfile
from threading import Thread
import warnings


class CartesianIO(CartesianCore):
    """This class provides IO-methods.

    Contains ``write_filetype`` and ``read_filetype`` methods
    like ``write_xyz()`` and ``read_xyz()``.

    The generic functions ``read`` and ``write``
    figure out themselves what the filetype is and use the
    appropiate IO-method.

    The ``view`` method uses external viewers to display a temporarily
    written xyz-file.
    """
    def _convert_nan_int(self):
        """The following functions are necessary to deal with the fact,
        that pandas does not support "NaN" for integers.
        It was written by the user LondonRob at StackExchange:
        http://stackoverflow.com/questions/25789354/
        exporting-ints-with-missing-values-to-csv-in-pandas/31208873#31208873
        Begin of the copied code snippet
        """
        COULD_BE_ANY_INTEGER = 0

        def _lost_precision(s):
            """The total amount of precision lost over Series `s`
            during conversion to int64 dtype
            """
            try:
                diff = (s - s.fillna(COULD_BE_ANY_INTEGER).astype(np.int64))
                return diff.sum()
            except ValueError:
                return np.nan

        def _nansafe_integer_convert(s, epsilon=1e-9):
            """Convert Series `s` to an object type with `np.nan`
            represented as an empty string
            """
            if _lost_precision(s) < epsilon:
                # Here's where the magic happens
                as_object = s.fillna(COULD_BE_ANY_INTEGER)
                as_object = as_object.astype(np.int64).astype(np.object)
                as_object[s.isnull()] = "nan"
                return as_object
            else:
                return s
        return self.apply(_nansafe_integer_convert)

    def to_string(self, buf=None, columns=None, col_space=None, header=True,
                  index=True, na_rep='NaN', formatters=None,
                  float_format=None, sparsify=None, index_names=True,
                  justify=None, line_width=None, max_rows=None,
                  max_cols=None, show_dimensions=False):
        """Render a DataFrame to a console-friendly tabular output.

        Wrapper around the :meth:`pandas.DataFrame.to_string` method.
        """
        return self._frame.to_string(
            buf=buf, columns=columns, col_space=col_space, header=header,
            index=index, na_rep=na_rep, formatters=formatters,
            float_format=float_format, sparsify=sparsify,
            index_names=index_names, justify=justify, line_width=line_width,
            max_rows=max_rows, max_cols=max_cols,
            show_dimensions=show_dimensions)

    def to_latex(self, buf=None, columns=None, col_space=None, header=True,
                 index=True, na_rep='NaN', formatters=None, float_format=None,
                 sparsify=None, index_names=True, bold_rows=True,
                 column_format=None, longtable=None, escape=None,
                 encoding=None, decimal='.', multicolumn=None,
                 multicolumn_format=None, multirow=None):
        """Render a DataFrame to a tabular environment table.

        You can splice this into a LaTeX document.
        Requires ``\\usepackage{booktabs}``.
        Wrapper around the :meth:`pandas.DataFrame.to_latex` method.
        """
        return self._frame.to_latex(
            buf=buf, columns=columns, col_space=col_space, header=header,
            index=index, na_rep=na_rep, formatters=formatters,
            float_format=float_format, sparsify=sparsify,
            index_names=index_names, bold_rows=bold_rows,
            column_format=column_format, longtable=longtable, escape=escape,
            encoding=encoding, decimal=decimal, multicolumn=multicolumn,
            multicolumn_format=multicolumn_format, multirow=multirow)

    def to_xyz(self, buf=None, sort_index=True,
               index=False, header=False, float_format='{:.6f}'.format,
               overwrite=True):
        """Write xyz-file

        Args:
            buf (str): StringIO-like, optional buffer to write to
            sort_index (bool): If sort_index is true, the
                :class:`~chemcoord.Cartesian`
                is sorted by the index before writing.
            float_format (one-parameter function): Formatter function
                to apply to column’s elements if they are floats.
                The result of this function must be a unicode string.
            overwrite (bool): May overwrite existing files.

        Returns:
            formatted : string (or unicode, depending on data and options)
        """
        create_string = '{n}\n{message}\n{alignment}{frame_string}'.format

        # TODO(automatically insert last stable version)
        message = 'Created by chemcoord \
http://chemcoord.readthedocs.io/en/latest/'

        if sort_index:
            molecule_string = self.sort_index().to_string(
                header=header, index=index, float_format=float_format)
        else:
            molecule_string = self.to_string(header=header, index=index,
                                             float_format=float_format)

        # NOTE the following might be removed in the future
        # introduced because of formatting bug in pandas
        # See https://github.com/pandas-dev/pandas/issues/13032
        space = ' ' * (self.loc[:, 'atom'].str.len().max()
                       - len(self.iloc[0, 0]))

        output = create_string(n=len(self), message=message,
                               alignment=space,
                               frame_string=molecule_string)

        if buf is not None:
            if overwrite:
                with open(buf, mode='w') as f:
                    f.write(output)
            else:
                with open(buf, mode='x') as f:
                    f.write(output)
        else:
            return output

    def write_xyz(self, *args, **kwargs):
        """Deprecated, use :meth:`~chemcoord.Cartesian.to_xyz`
        """
        message = 'Will be removed in the future. Please use to_xyz().'
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.warn(message, DeprecationWarning)
        return self.to_xyz(*args, **kwargs)

    @classmethod
    def read_xyz(cls, inputfile, start_index=0, get_bonds=True):
        """Read a file of coordinate information.

        Reads xyz-files.

        Args:
            inputfile (str):
            start_index (int):
            get_bonds (bool):

        Returns:
            Cartesian:
        """
        frame = pd.read_table(inputfile, skiprows=2, comment='#',
                              delim_whitespace=True,
                              names=['atom', 'x', 'y', 'z'])

        molecule = cls(frame)
        molecule.index = range(start_index, start_index + len(molecule))

        if get_bonds:
            molecule.get_bonds(use_lookup=False, set_lookup=True)
        return molecule

    def view(self, viewer=settings['defaults']['viewer'], use_curr_dir=False):
        """View your molecule.

        .. note:: This function writes a temporary file and opens it with
            an external viewer.
            If you modify your molecule afterwards you have to recall view
            in order to see the changes.

        Args:
            viewer (str): The external viewer to use. The default is
                specified in cc.settings.settings['viewer']
            use_curr_dir (bool): If True, the temporary file is written to
                the current diretory. Otherwise it gets written to the
                OS dependendent temporary directory.

        Returns:
            None:
        """
        if use_curr_dir:
            TEMP_DIR = os.path.curdir
        else:
            TEMP_DIR = tempfile.gettempdir()

        def give_filename(i):
            filename = 'ChemCoord_' + str(i) + '.xyz'
            return os.path.join(TEMP_DIR, filename)

        i = 1
        while os.path.exists(give_filename(i)):
            i = i + 1
        self.to_xyz(give_filename(i))

        def open_file(i):
            """Open file and close after being finished."""
            try:
                subprocess.check_call([viewer, give_filename(i)])
            except (subprocess.CalledProcessError, FileNotFoundError):
                raise
            finally:
                if use_curr_dir:
                    pass
                else:
                    os.remove(give_filename(i))

        Thread(target=open_file, args=(i,)).start()
