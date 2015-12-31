""" Wrappers around Esri's ``arcpy`` library.

This contains basic file I/O, coversion, and spatial analysis functions
to support the python-propagator library. These functions generally
are simply wrappers around their ``arcpy`` counter parts. This was done
so that in the future, these functions could be replaced with calls to
a different geoprocessing library and eventually ween the code base off
of its ``arcpy`` dependency.

(c) Geosyntec Consultants, 2015.

Released under the BSD 3-clause license (see LICENSE file for more info)

Written by Paul Hobson (phobson@geosyntec.com)

"""


import os
import itertools
from contextlib import contextmanager

import numpy

import arcpy

from . import misc
from propagator import validate


class RasterTemplate(object):
    """ Georeferencing template for Rasters.

    This mimics the attributes of teh ``arcpy.Raster`` class enough
    that it can be used as a template to georeference numpy arrays
    when converting to rasters.

    Parameters
    ----------
    cellsize : int or float
        The width of the raster's cells.
    xmin, ymin : float
        The x- and y-coordinates of the raster's lower left (south west)
        corner.

    Attributes
    ----------
    cellsize : int or float
        The width of the raster's cells.
    extent : Extent
        Yet another mock-ish class that ``x`` and ``y`` are stored in
        ``extent.lowerLeft`` as an ``arcpy.Point``.

    See also
    --------
    arcpy.Extent

    """

    def __init__(self, cellsize, xmin, ymin):
        self.meanCellWidth = cellsize
        self.meanCellHeight = cellsize
        self.extent = arcpy.Extent(xmin, ymin, numpy.nan, numpy.nan)

    @classmethod
    def from_raster(cls, raster):
        """ Alternative constructor to generate a RasterTemplate from
        an actual raster.

        Parameters
        ----------
        raster : arcpy.Raster
            The raster whose georeferencing attributes need to be
            replicated.

        Returns
        -------
        template : RasterTemplate

        """
        template = cls(
            raster.meanCellHeight,
            raster.extent.lowerLeft.X,
            raster.extent.lowerLeft.Y,
        )
        return template


class EasyMapDoc(object):
    """ The object-oriented map class Esri should have made.

    Create this the same you would make any other
    `arcpy.mapping.MapDocument`_. But now, you can directly list and
    add layers and dataframes. See the two examples below.

    Has ``layers`` and ``dataframes`` attributes that return all of the
    `arcpy.mapping.Layer`_ and `arcpy.mapping.DataFrame`_ objects in the
    map, respectively.

    .. _arcpy.mapping.MapDocument: http://goo.gl/rf4GBH
    .. _arcpy.mapping.DataFrame: http://goo.gl/ctJu3B
    .. _arcpy.mapping.Layer: http://goo.gl/KfrGNa

    Attributes
    ----------
    mapdoc : arcpy.mapping.MapDocument
        The underlying arcpy MapDocument that serves as the basis for
        this class.

    Examples
    --------
    >>> # Adding a layer with the Esri version:
    >>> import arpcy
    >>> md = arcpy.mapping.MapDocument('CURRENT')
    >>> df = arcpy.mapping.ListDataFrames(md)
    >>> arcpy.mapping.AddLayer(df, myLayer, 'TOP')

    >>> # And now with an ``EasyMapDoc``:
    >>> from tidegates import utils
    >>> ezmd = utils.EasyMapDoc('CURRENT')
    >>> ezmd.add_layer(myLayer)

    """

    def __init__(self, *args, **kwargs):
        try:
            self.mapdoc = arcpy.mapping.MapDocument(*args, **kwargs)
        except RuntimeError:
            self.mapdoc = None

    @property
    def layers(self):
        """
        All of the layers in the map.
        """
        return arcpy.mapping.ListLayers(self.mapdoc)

    @property
    def dataframes(self):
        """
        All of the dataframes in the map.
        """
        return arcpy.mapping.ListDataFrames(self.mapdoc)

    def findLayerByName(self, name):
        """ Finds a `layer`_ in the map by searching for an exact match
        of its name.

        .. _layer: http://goo.gl/KfrGNa

        Parameters
        ----------
        name : str
            The name of the layer you want to find.

        Returns
        -------
        lyr : arcpy.mapping.Layer
            The map layer or None if no match is found.

        .. warning:: Group Layers are not returned.

        Examples
        --------
        >>> from tidegates import utils
        >>> ezmd = utils.EasyMapDoc('CURRENT')
        >>> wetlands = ezmd.findLayerByName("wetlands")
        >>> if wetlands is not None:
        ...     # do something with `wetlands`

        """

        for lyr in self.layers:
            if not lyr.isGroupLayer and lyr.name == name:
                return lyr

    def add_layer(self, layer, df=None, position='top'):
        """ Simply adds a `layer`_ to a map.

        .. _layer: http://goo.gl/KfrGNa

        Parameters
        ----------
        layer : str or arcpy.mapping.Layer
            The dataset to be added to the map.
        df : arcpy.mapping.DataFrame, optional
            The specific dataframe to which the layer will be added. If
            not provided, the data will be added to the first dataframe
            in the map.
        position : str, optional ('TOP')
            The positional within `df` where the data will be added.
            Valid options are: 'auto_arrange', 'bottom', and 'top'.

        Returns
        -------
        layer : arcpy.mapping.Layer
            The sucessfully added layer.

        Examples
        --------
        >>> from tidegates import utils
        >>> ezmd = utils.EasyMapDoc('CURRENT')
        >>> ezmd.add_layer(myLayer)

        """

        # if no dataframe is provided, select the first
        if df is None:
            df = self.dataframes[0]

        # check that the position is valid
        valid_positions = ['auto_arrange', 'bottom', 'top']
        if position.lower() not in valid_positions:
            raise ValueError('Position: %s is not in %s' % (position.lower, valid_positions))

        # layer can be a path to a file. if so, convert to a Layer object
        layer = load_data(layer, 'layer')

        # add the layer to the map
        arcpy.mapping.AddLayer(df, layer, position.upper())

        # return the layer
        return layer


@contextmanager
def Extension(name):
    """ Context manager to facilitate the use of ArcGIS extensions

    Inside the context manager, the extension will be checked out. Once
    the interpreter leaves the code block by any means (e.g., sucessful
    execution, raised exception) the extension will be checked back in.

    Examples
    --------
    >>> import tidegates, arcpy
    >>> with tidegates.utils.Extension("spatial"):
    ...     arcpy.sa.Hillshade("C:/data/dem.tif")

    """

    if arcpy.CheckExtension(name) == u"Available":
        status = arcpy.CheckOutExtension(name)
        yield status
    else:
        raise RuntimeError("%s license isn't available" % name)

    arcpy.CheckInExtension(name)


@contextmanager
def OverwriteState(state):
    """ Context manager to temporarily set the ``overwriteOutput``
    environment variable.

    Inside the context manager, the ``arcpy.env.overwriteOutput`` will
    be set to the given value. Once the interpreter leaves the code
    block by any means (e.g., sucessful execution, raised exception),
    ``arcpy.env.overwriteOutput`` will reset to its original value.

    Parameters
    ----------
    path : str
        Path to the directory that will be set as the current workspace.

    Examples
    --------
    >>> import tidegates
    >>> with tidegates.utils.OverwriteState(False):
    ...     # some operation that should fail if output already exists

    """

    orig_state = arcpy.env.overwriteOutput
    arcpy.env.overwriteOutput = bool(state)
    yield
    arcpy.env.overwriteOutput = orig_state


@contextmanager
def WorkSpace(path):
    """ Context manager to temporarily set the ``workspace``
    environment variable.

    Inside the context manager, the `arcpy.env.workspace`_ will
    be set to the given value. Once the interpreter leaves the code
    block by any means (e.g., sucessful execution, raised exception),
    `arcpy.env.workspace`_ will reset to its original value.

    .. _arcpy.env.workspace: http://goo.gl/0NpeFN

    Parameters
    ----------
    path : str
        Path to the directory that will be set as the current workspace.

    Examples
    --------
    >>> import tidegates
    >>> with tidegates.utils.OverwriteState(False):
    ...     # some operation that should fail if output already exists

    """

    orig_workspace = arcpy.env.workspace
    arcpy.env.workspace = path
    yield
    arcpy.env.workspace = orig_workspace


def create_temp_filename(filepath, filetype=None, prefix='_temp_', num=None):
    """ Helper function to create temporary filenames before to be saved
    before the final output has been generated.

    Parameters
    ----------
    filepath : str
        The file path/name of what the final output will eventually be.
    filetype : str, optional
        The type of file to be created. Valid values: "Raster" or
        "Shape".
    prefix : str, optional ('_temp_')
        The prefix that will be applied to ``filepath``.
    num : int, optional
        A file "number" that can be appended to the very end of the
        filename.

    Returns
    -------
    str

    Examples
    --------
    >>> create_temp_filename('path/to/flooded_wetlands', filetype='shape')
    path/to/_temp_flooded_wetlands.shp

    """

    file_extensions = {
        'raster': '.tif',
        'shape': '.shp'
    }

    if num is None:
        num = ''
    else:
        num = '_{}'.format(num)

    ws = arcpy.env.workspace or '.'
    filename, _ = os.path.splitext(os.path.basename(filepath))
    folder = os.path.dirname(filepath)
    if folder != '':
        final_workspace = os.path.join(ws, folder)
    else:
        final_workspace = ws

    if os.path.splitext(final_workspace)[1] == '.gdb':
        ext = ''
    else:
        ext = file_extensions[filetype.lower()]


    return os.path.join(ws, folder, prefix + filename + num + ext)


def check_fields(table, *fieldnames, **kwargs):
    """
    Checks that field are (or are not) in a table. The check fails, a
    ``ValueError`` is raised.

    Parameters
    ----------
    table : arcpy.mapping.Layer or similar
        Any table-like that we can pass to `arcpy.ListFields`.
    *fieldnames : str arguments
        optional string arguments that whose existance in `table` will
        be checked.
    should_exist : bool, optional (False)
        Whether we're testing for for absense (False) or existance
        (True) of the provided field names.

    Returns
    -------
    None

    """

    should_exist = kwargs.pop('should_exist', False)

    existing_fields = get_field_names(table)
    bad_names = []
    for name in fieldnames:
        exists = name in existing_fields
        if should_exist != exists and name != 'SHAPE@AREA':
            bad_names.append(name)

    if not should_exist:
        qual = 'already'
    else:
        qual = 'not'

    if len(bad_names) > 0:
        raise ValueError('fields {} are {} in {}'.format(bad_names, qual, table))


@misc.update_status() # raster
def result_to_raster(result):
    """ Gets the actual `arcpy.Raster`_ from an `arcpy.Result`_ object.

    .. _arcpy.Raster: http://goo.gl/AQgFXW
    .. _arcpy.Result: http://goo.gl/xPIbHi

    Parameters
    ----------
    result : arcpy.Result
        The `Result` object returned from some other geoprocessing
        function.

    Returns
    -------
    arcpy.Raster

    See also
    --------
    result_to_layer

    """
    return arcpy.Raster(result.getOutput(0))


@misc.update_status() # layer
def result_to_layer(result):
    """ Gets the actual `arcpy.mapping.Layer`_ from an `arcpy.Result`_
    object.

    .. _arcpy.mapping.Layer: http://goo.gl/KfrGNa
    .. _arcpy.Result: http://goo.gl/xPIbHi

    Parameters
    ----------
    result : arcpy.Result
        The `Result` object returned from some other geoprocessing
        function.

    Returns
    -------
    arcpy.mapping.Layer

    See also
    --------
    result_to_raster

    """

    return arcpy.mapping.Layer(result.getOutput(0))


@misc.update_status() # list of arrays
def rasters_to_arrays(*rasters, **kwargs):
    """ Converts an arbitrary number of `rasters`_ to `numpy arrays`_.
    Relies on `arcpy.RasterToNumPyArray`_.

    .. _rasters: http://goo.gl/AQgFXW
    .. _numpy arrays: http://goo.gl/iaDlli
    .. _arcpy.RasterToNumPyArray: http://goo.gl/nXjo8N

    Parameters
    ----------
    rasters : args of numpy.arrays
        Rasters that will be converted to arrays.
    squeeze : bool, optional (False)
        By default (``squeeze = False``) a list of arrays is always
        returned. However, when ``squeeze = True`` and only one raster
        is provided, the array will be **squeezed** out of the list
        and returned directly.

    Returns
    -------
    arrays : list of arrays or array.

    See also
    --------
    array_to_raster
    result_to_raster
    polygons_to_raster

    """

    squeeze = kwargs.pop("squeeze", False)

    arrays = []
    for n, r in enumerate(rasters):
        arrays.append(arcpy.RasterToNumPyArray(r, nodata_to_value=-999))

    if squeeze and len(arrays) == 1:
        arrays = arrays[0]

    return arrays


@misc.update_status() # raster
def array_to_raster(array, template, outfile=None):
    """ Create an arcpy.Raster from a numpy.ndarray based on a template.
    This wrapper around `arcpy.NumPyArrayToRaster`_.

    .. _arcpy.NumPyArrayToRaster: http://goo.gl/xQsaIz

    Parameters
    ----------
    array : numpy.ndarray
        The array of values to be coverted to a raster.
    template : arcpy.Raster or RasterTemplate
        The raster whose, extent, position, and cell size will be
        applied to ``array``.

    Returns
    -------
    newraster : arcpy.Raster

    See also
    --------
    RasterTemplate
    rasters_to_arrays
    polygons_to_raster

    Examples
    --------
    >>> from tidegates import utils
    >>> raster = utils.load_data('dem.tif', 'raster') # in meters
    >>> array = utils.rasters_to_arrays(raster, squeeze=True)
    >>> array = array / 0.3048 # convert elevations to feet
    >>> newraster = utils.array_to_raster(array, raster)
    >>> newraster.save('<path_to_output>')

    """

    newraster = arcpy.NumPyArrayToRaster(
        in_array=array,
        lower_left_corner=template.extent.lowerLeft,
        x_cell_size=template.meanCellWidth,
        y_cell_size=template.meanCellHeight,
        value_to_nodata=0
    )

    if outfile is not None:
        newraster.save(outfile)

    return newraster


@misc.update_status() # raster or layer
def load_data(datapath, datatype, greedyRasters=True, **verbosity):
    """ Loads vector and raster data from filepaths.

    Parameters
    ----------
    datapath : str, arcpy.Raster, or arcpy.mapping.Layer
        The (filepath to the) data you want to load.
    datatype : str
        The type of data you are trying to load. Must be either
        "shape" (for polygons) or "raster" (for rasters).
    greedyRasters : bool (default = True)
        Currently, arcpy lets you load raster data as a "Raster" or as a
        "Layer". When ``greedyRasters`` is True, rasters loaded as type
        "Layer" will be forced to type "Raster".

    Returns
    -------
    data : `arcpy.Raster`_ or `arcpy.mapping.Layer`_
        The data loaded as an arcpy object.

    .. _arcpy.Raster: http://goo.gl/AQgFXW
    .. _arcpy.mapping.Layer: http://goo.gl/KfrGNa

    """

    dtype_lookup = {
        'raster': arcpy.Raster,
        'grid': arcpy.Raster,
        'shape': arcpy.mapping.Layer,
        'layer': arcpy.mapping.Layer,
    }

    try:
        objtype = dtype_lookup[datatype.lower()]
    except KeyError:
        msg = "Datatype {} not supported. Must be raster or layer".format(datatype)
        raise ValueError(msg)

    # if the input is already a Raster or Layer, just return it
    if isinstance(datapath, objtype):
        data = datapath
    # otherwise, load it as the datatype
    else:
        try:
            data = objtype(datapath)
        except:
            raise ValueError("could not load {} as a {}".format(datapath, objtype))

    if greedyRasters and isinstance(data, arcpy.mapping.Layer) and data.isRasterLayer:
        data = arcpy.Raster(datapath)

    return data


@misc.update_status() # raster
def polygons_to_raster(polygons, ID_column, cellsize=4, outfile=None):
    """ Prepare tidegates' areas of influence polygons for flooding
    by converting to a raster. Relies on
    `arcpy.conversion.PolygonToRaster`_.

    .. _arcpy.conversion.PolygonToRaster: http://goo.gl/TG2wD7

    Parameters
    ----------
    polygons : str or arcpy.mapping.Layer
        The (filepath to the) zones that will be flooded. If a string,
        a Layer will be created.
    ID_column : str
        Name of the column in the ``polygons`` layer that associates
        each geomstry with a tidegate.
    cellsize : int
        Desired cell dimension of the output raster. Default is 4 m.

    Returns
    -------
    zones : arcpy.Raster
        The zones of influence as a raster dataset
    result : arcpy.Result
        The weird, crpyric results object that so many (but not all)
        ESRI arcpy function return.

    Examples
    --------
    >>> zone_raster, res = utils.polygons_to_raster('ZOI.shp', 'GeoID')
    >>> zone_array = utils.rasters_to_arrays(zone_raster, squeeze=True)
    >>> # remove all zones with a GeoID less than 5
    >>> zone_array[zone_array < 5] = 0
    >>> filtered_raster = utils.array_to_raster(zone_array, zone_raster)

    See also
    --------
    raster_to_polygons
    rasters_to_arrays
    array_to_raster

    """

    _zones = load_data(polygons, 'shape')

    with OverwriteState(True), Extension("spatial"):
        result = arcpy.conversion.PolygonToRaster(
            in_features=_zones,
            value_field=ID_column,
            cellsize=cellsize,
            out_rasterdataset=outfile,
        )

    zones = result_to_raster(result)

    return zones


@misc.update_status() # raster
def clip_dem_to_zones(dem, zones, outfile=None):
    """ Limits the extent of the topographic data (``dem``) to that of
    the zones of influence  so that we can easily use array
    representations of the rasters. Relies on `arcpy.management.Clip`_.

    .. _arcpy.management.Clip: http://goo.gl/md4nFF

    Parameters
    ----------
    dem : arcpy.Raster
        Digital elevation model of the area of interest.
    zones : arcpy.Raster
        The raster whose cell values represent the zones of influence
        of each tidegate.

    Returns
    -------
    dem_clipped : arcpy.Raster
        The zones of influence as a raster dataset
    result : arcpy.Result
        The weird, cryptic results object that so many (but not all)
        ESRI arcpy function return.

    """

    _dem = load_data(dem, "raster")
    _zones = load_data(zones, "raster")

    with OverwriteState(True) as state:
        result = arcpy.management.Clip(
            in_raster=_dem,
            in_template_dataset=_zones,
            out_raster=outfile,
            maintain_clipping_extent="MAINTAIN_EXTENT",
            clipping_geometry="NONE",
        )

    dem_clipped = result_to_raster(result)

    return dem_clipped


@misc.update_status() # layer
def raster_to_polygons(zonal_raster, filename, newfield=None):
    """
    Converts zonal rasters to polygons layers. This is basically just
    a thing wrapper around arcpy.conversion.RasterToPolygon. The
    returned layers will have a field that corresponds to the values of
    the raster. The name of this field can be controlled with the
    ``newfield`` parameter.

    Relies on `arcpy.conversion.RasterToPolygon`_.

    .. _arcpy.conversion.RasterToPolygon: http://goo.gl/QOeOCq


    Parameters
    ----------
    zonal_raster : arcpy.Raster
        An integer raster of reasonably small set distinct values.
    filename : str
        Path to where the polygons will be saved.
    newfield : str, optional
        By default, the field that contains the raster values is called
        "gridcode". Use this parameter to change the name of that field.

    Returns
    -------
    polygons : arcpy.mapping.Layer
        The converted polygons.

    See also
    --------
    polygons_to_raster
    add_field_with_value
    populate_field

    """

    with OverwriteState(True), Extension("spatial"):
        results = arcpy.conversion.RasterToPolygon(
            in_raster=zonal_raster,
            out_polygon_features=filename,
            simplify="SIMPLIFY",
            raster_field="Value",
        )

    if newfield is not None:
        for fieldname in get_field_names(filename):
            if fieldname.lower() == 'gridcode':
                gridfield = fieldname

        add_field_with_value(filename, newfield, field_type="LONG")
        populate_field(filename, lambda x: x[0], newfield, gridfield)

    polygons = result_to_layer(results)
    return polygons


@misc.update_status() # layer
def aggregate_polygons(polygons, ID_field, filename):
    """
    Dissolves (aggregates) polygons into a single feature the unique
    values in the provided field. This is basically just a thim wrapper
    around `arcpy.management.Dissolve`_.

    .. _arcpy.management.Dissolve: http://goo.gl/tsmiQH

    Parameters
    ----------
    polygons : arcpy.mapping.Layer
        The layer of polygons to be aggregated.
    ID_field : string
        The name of the field in ``polygons`` on which the individual
        polygons will be grouped.
    filename : string
        Path to where the aggregated polygons will be saved.

    Returns
    -------
    dissolved : arcpy.mapping.Layer
        The aggregated polygons.

    Examples
    --------
    >>> from tidegates import utils
    >>> dissolved = utils.aggregate_polygons('wetlands.shp', 'GeoID',
    ...                                      'dissolved.shp')

    See also
    --------
    arcpy.management.Dissolve

    """

    results = arcpy.management.Dissolve(
        in_features=polygons,
        dissolve_field=ID_field,
        out_feature_class=filename,
        statistics_fields='#'
    )

    dissolved = result_to_layer(results)
    return dissolved


@misc.update_status() # None
def add_field_with_value(table, field_name, field_value=None,
                         overwrite=False, **field_opts):
    """ Adds a numeric or text field to an attribute table and sets it
    to a constant value. Operates in-place and therefore does not
    return anything.

    Relies on `arcpy.management.AddField`_.

    .. _arcpy.management.AddField: http://goo.gl/wivgDX

    Parameters
    ----------
    table : Layer, table, or file path
        This is the layer/file that will have a new field created.
    field_name : string
        The name of the field to be created.
    field_value : float or string, optional
        The value of the new field. If provided, it will be used to
        infer the ``field_type`` parameter required by
        `arcpy.management.AddField` if ``field_type`` is itself not
        explicitly provided.
    overwrite : bool, optonal (False)
        If True, an existing field will be overwritten. The default
        behavior will raise a `ValueError` if the field already exists.
    **field_opts : keyword options
        Keyword arguments that are passed directly to
        `arcpy.management.AddField`.

    Returns
    -------
    None

    Examples
    --------
    >>> # add a text field to shapefile (text fields need a length spec)
    >>> utils.add_field_with_value("mypolygons.shp", "storm_event",
                                   "100-yr", field_length=10)
    >>> # add a numeric field (doesn't require additional options)
    >>> utils.add_field_with_value("polygons.shp", "flood_level", 3.14)

    """

    # how Esri map python types to field types
    typemap = {
        int: 'LONG',
        float: 'DOUBLE',
        unicode: 'TEXT',
        str: 'TEXT',
        type(None): None
    }

    # pull the field type from the options if it was specified,
    # otherwise lookup a type based on the `type(field_value)`.
    field_type = field_opts.pop("field_type", typemap[type(field_value)])

    if not overwrite:
        check_fields(table, field_name, should_exist=False)

    if field_value is None and field_type is None:
        raise ValueError("must provide a `field_type` if not providing a value.")

    # see http://goo.gl/66QD8c
    arcpy.management.AddField(
        in_table=table,
        field_name=field_name,
        field_type=field_type,
        **field_opts
    )

    # set the value in all rows
    if field_value is not None:
        populate_field(table, lambda row: field_value, field_name)


@misc.update_status() # None
def cleanup_temp_results(*results):
    """ Deletes temporary results from the current workspace.

    Relies on `arcpy.management.Delete`_.

    .. _arcpy.management.Delete: http://goo.gl/LW85an

    Parameters
    ----------
    *results : str
        Paths to the temporary results

    Returns
    -------
    None

    """
    for r in results:
        if isinstance(r, basestring):
            path = r
        elif isinstance(r, arcpy.Result):
            path = r.getOutput(0)
        elif isinstance(r, arcpy.mapping.Layer):
            path = r.dataSource
        elif isinstance(r, arcpy.Raster):
            # Esri docs are incorrect here:
            # --> http://goo.gl/67NwDj
            # path doesn't include the name
            path = os.path.join(r.path, r.name)
        else:
            raise ValueError("Input must be paths, Results, Rasters, or Layers")

        fullpath = os.path.join(os.path.abspath(arcpy.env.workspace), path)
        arcpy.management.Delete(fullpath)


@misc.update_status() # layer
def intersect_polygon_layers(destination, *layers, **intersect_options):
    """
    Intersect polygon layers with each other. Basically a thin wrapper
    around `arcpy.analysis.Intersect`_.

    .. _arcpy.analysis.Intersect: http://goo.gl/O9YMY6

    Parameters
    ----------
    destination : str
        Filepath where the intersected output will be saved.
    *layers : str or arcpy.Mapping.Layer
        The polygon layers (or their paths) that will be intersected
        with each other.
    **intersect_options : keyword arguments
        Additional arguments that will be passed directly to
        `arcpy.analysis.Intersect`.

    Returns
    -------
    intersected : arcpy.mapping.Layer
        The arcpy Layer of the intersected polygons.

    Examples
    --------
    >>> from tidedates import utils
    >>> blobs = utils.intersect_polygon_layers(
    ...     "flood_damage_intersect.shp"
    ...     "floods.shp",
    ...     "wetlands.shp",
    ...     "buildings.shp"
    ... )

    """

    result = arcpy.analysis.Intersect(
        in_features=layers,
        out_feature_class=destination,
        **intersect_options
    )

    intersected = result_to_layer(result)
    return intersected


@misc.update_status() # record array
def load_attribute_table(input_path, *fields):
    """
    Loads a shapefile's attribute table as a numpy record array.

    Relies on `arcpy.da.TableToNumPyArray`_.

    .. _arcpy.da.TableToNumPyArray: http://goo.gl/NzS6sB

    Parameters
    ----------
    input_path : str
        Fiilepath to the shapefile or feature class whose table needs
        to be read.
    *fields : str
        Names of the fields that should be included in the resulting
        array.

    Returns
    -------
    records : numpy.recarray
        A record array of the selected fields in the attribute table.

    See also
    --------
    groupby_and_aggregate

    Examples
    --------
    >>> from propagator import utils
    >>> path = "data/subcatchment.shp"
    >>> catchements = utils.load_attribute_table(path, 'CatchID',
    ... 'DwnCatchID', 'Watershed')
    >>> catchements[:5]
    array([(u'541', u'571', u'San Juan Creek'),
           (u'754', u'618', u'San Juan Creek'),
           (u'561', u'577', u'San Juan Creek'),
           (u'719', u'770', u'San Juan Creek'),
           (u'766', u'597', u'San Juan Creek')],
          dtype=[('CatchID', '<U20'), ('DwnCatchID', '<U20'),
                 ('Watershed', '<U50')])
    """
    # load the data
    layer = load_data(input_path, "layer")

    if len(fields) == 0:
        fields = get_field_names(input_path)

    # check that fields are valid
    check_fields(layer.dataSource, *fields, should_exist=True)

    array = arcpy.da.FeatureClassToNumPyArray(in_table=input_path, field_names=fields)
    return array


@misc.update_status() # dict
def groupby_and_aggregate(input_path, groupfield, valuefield,
                          aggfxn=None):
    """
    Counts the number of distinct values of `valuefield` are associated
    with each value of `groupfield` in a data source found at
    `input_path`.

    Parameters
    ----------
    input_path : str
        File path to a shapefile or feature class whose attribute table
        can be loaded with `arcpy.da.TableToNumPyArray`.
    groupfield : str
        The field name that would be used to group all of the records.
    valuefield : str
        The field name whose distinct values will be counted in each
        group defined by `groupfield`.
    aggfxn : callable, optional.
        Function to aggregate the values in each group to a single group.
        This function should accept an `itertools._grouper` as its only
        input. If not provided, unique number of value in the group will
        be returned.

    Returns
    -------
    counts : dict
        A dictionary whose keys are the distinct values of `groupfield`
        and values are the number of distinct records in each group.

    Examples
    --------
    >>> # compute total areas for each 'GeoID'
    >>> wetland_areas = utils.groupby_and_aggregate(
    ...     input_path='wetlands.shp',
    ...     groupfield='GeoID',
    ...     valuefield='SHAPE@AREA',
    ...     aggfxn=lambda group: sum([row[1] for row in group])
    ... )

    >>> # count the number of structures associated with each 'GeoID'
    >>> building_counts = utils.groupby_and_aggregate(
    ...     input_path=buildingsoutput,
    ...     groupfield=ID_column,
    ...     valuefield='STRUCT_ID'
    ... )

    See also
    --------
    itertools.groupby
    populate_field
    load_attribute_table

    """

    if aggfxn is None:
        aggfxn = lambda x: int(numpy.unique(list(x)).shape[0])

    table = load_attribute_table(input_path, groupfield, valuefield)
    table.sort()

    counts = {}
    for groupname, shapes in itertools.groupby(table, lambda row: row[groupfield]):
        counts[groupname] = aggfxn(shapes)

    return counts


@misc.update_status() # None
def rename_column(table, oldname, newname, newalias=None): # pragma: no cover
    """
    .. warning: Not yet implemented.
    """
    raise NotImplementedError
    if newalias is None:
        newalias = newname

    oldfield = filter(lambda f: name == oldname, get_field_names(table))[0]

    arcpy.management.AlterField(
        in_table=table,
        field=oldfield,
        new_field_name=newname,
        new_field_alias=newalias
    )


@misc.update_status() # None
def populate_field(table, value_fxn, valuefield, *keyfields):
    """
    Loops through the records of a table and populates the value of one
    field (`valuefield`) based on another field (`keyfield`) by passing
    the entire row through a function (`value_fxn`).

    Relies on `arcpy.da.UpdateCursor`_.

    .. _arcpy.da.UpdateCursor: http://goo.gl/sa3mW6

    Parameters
    ----------
    table : Layer, table, or file path
        This is the layer/file that will have a new field created.
    value_fxn : callable
        Any function that accepts a row from an `arcpy.da.SearchCursor`
        and returns a *single* value.
    valuefield : string
        The name of the field to be computed.
    *keyfields : strings, optional
        The other fields that need to be present in the rows of the
        cursor.

    Returns
    -------
    None

    .. note::
       In the row object, the `valuefield` will be the last item.
       In other words, `row[0]` will return the first values in
       `*keyfields` and `row[-1]` will return the existing value of
       `valuefield` in that row.

    Examples
    --------
    >>> # populate field ("Company") with a constant value ("Geosyntec")
    >>> populate_field("wetlands.shp", lambda row: "Geosyntec", "Company")

    """

    fields = list(keyfields)
    fields.append(valuefield)
    check_fields(table, *fields, should_exist=True)

    with arcpy.da.UpdateCursor(table, fields) as cur:
        for row in cur:
            row[-1] = value_fxn(row)
            cur.updateRow(row)


@misc.update_status()
def copy_layer(existing_layer, new_layer):
    """
    Makes copies of features classes, shapefiles, and maybe rasters.

    Parameters
    ----------
    existing_layer : str
        Path to the data to be copied
    new_layer : str
        Path to where ``existing_layer`` should be copied.

    Returns
    -------
    new_layer : str

    """

    arcpy.management.Copy(in_data=existing_layer, out_data=new_layer)
    return new_layer

@misc.update_status() # layer
def concat_results(destination, *input_files):
    """ Concatentates (merges) serveral datasets into a single shapefile
    or feature class.

    Relies on `arcpy.management.Merge`_.

    .. _arcpy.management.Merge: http://goo.gl/JD3q0f

    Parameters
    ----------
    destination : str
        Path to where the concatentated dataset should be saved.
    *input_files : str
        Strings of the paths of the datasets to be merged.

    Returns
    -------
    arcpy.mapping.Layer

    See also
    --------
    join_results_to_baseline

    """

    result = arcpy.management.Merge(input_files, destination)
    return result_to_layer(result)


def update_attribute_table(layerpath, attribute_array, id_column, *update_columns):
    """
    Update the attribute table of a feature class from a record array.

    Parameters
    ----------
    layerpath : str
        Path to the feature class to be updated.
    attribute_array : numpy.recarray
        A record array that contains the data to be writted into
        ``layerpath``.
    id_column : str
        The name of the column that uniquely identifies each feature in
        both ``layerpath`` and ``attribute_array``.
    *update_columns : str
        Names of the columns in both ``layerpath`` and
        ``attribute_array`` that will be updated.

    Returns
    -------
    None

    """

    # place the ID_column and columnes to be updated
    # in a single list
    all_columns = [id_column]
    all_columns.extend(update_columns)

    # load the existing attributed table, loop through all rows
    with arcpy.da.UpdateCursor(layerpath, all_columns) as cur:
        for oldrow in cur:
            # find the current row in the new array
            newrow = misc.find_row_in_array(attribute_array, id_column, oldrow[0])
            # loop through the value colums, setting them to the new values
            if newrow is not None:
                for n, col in enumerate(update_columns, 1):
                    oldrow[n] = newrow[col]

            # update the row
            cur.updateRow(oldrow)

    return layerpath


def delete_columns(layerpath, *columns):
    """
    Delete unwanted fields from an attribute table of a feature class.

    Parameters
    ----------
    layerpath : str
        Path to the feature class to be updated.
    *columns : str
        Names of the columns in ``layerpath`` that will be deleted

    Returns
    -------
    None

    """
    if len(columns) > 0:
        col_str = ";".join(columns)
        arcpy.management.DeleteField(layerpath, col_str)

    return layerpath


def spatial_join(left, right, outputfile, **kwargs):
    arcpy.analysis.SpatialJoin(
        target_features=left,
        join_features=right,
        out_feature_class=outputfile,
        **kwargs
    )

    return outputfile


def count_features(layer):
    return int(arcpy.management.GetCount(layer).getOutput(0))


def query_layer(inputpath, outputpath, sql):
    arcpy.analysis.Select(
        in_features=inputpath,
        out_feature_class=outputpath,
        where_clause=sql
    )

    return outputpath


def intersect_layers(input_paths, output_path, how='all'):
    arcpy.analysis.Intersect(
        in_features=input_paths,
        out_feature_class=output_path,
        join_attributes=how.upper(),
        output_type="INPUT"
    )

    return output_path


def get_field_names(layerpath):
    """
    Gets the names of fields/columns in a feature class or table.
    Relies on `arcpy.ListFields`_.

    .. _arcpy.ListFields: http://goo.gl/Siq5y7

    Parameters
    ----------
    layerpath : str, arcpy.Layer, or arcpy.table
        The thing that has fields.

    Returns
    -------
    fieldnames : list of str

    """

    return [f.name for f in arcpy.ListFields(layerpath)]
