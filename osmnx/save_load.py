################################################################################
# Module: save_load.py
# Description: Save and load networks to/from disk
# License: MIT, see full license in LICENSE.txt
# Web: https://github.com/gboeing/osmnx
################################################################################

import re
import time
import os
import ast
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
from shapely.geometry import Point
from shapely.geometry import LineString
from shapely import wkt

from . import settings
from .utils import log
from .utils import make_str


def save_gdf_shapefile(gdf, filename=None, folder=None):
    """
    Save a GeoDataFrame of place shapes or building footprints as an ESRI
    shapefile.

    Parameters
    ----------
    gdf : GeoDataFrame
        the gdf to be saved
    filename : string
        what to call the shapefile (file extensions are added automatically)
    folder : string
        where to save the shapefile, if none, then default folder

    Returns
    -------
    None
    """

    if folder is None:
        folder = settings.data_folder

    if filename is None:
        filename = make_shp_filename(gdf.gdf_name)

    # give the save folder a filename subfolder to make the full path to the
    # files
    folder_path = os.path.join(folder, filename)

    # make everything but geometry column a string
    for col in [c for c in gdf.columns if not c == 'geometry']:
        gdf[col] = gdf[col].fillna('').map(make_str)

    # if the save folder does not already exist, create it with a filename
    # subfolder
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    gdf.to_file(folder_path)

    if not hasattr(gdf, 'gdf_name'):
        gdf.gdf_name = 'unnamed'
    log('Saved the GeoDataFrame "{}" as shapefile "{}"'.format(gdf.gdf_name, folder_path))


def save_graph_shapefile(G, filename='graph', folder=None, encoding='utf-8'):
    """
    Save graph nodes and edges as ESRI shapefiles to disk.

    Parameters
    ----------
    G : networkx multidigraph
    filename : string
        the name of the shapefiles (not including file extensions)
    folder : string
        the folder to contain the shapefiles, if None, use default data folder
    encoding : string
        the character encoding for the saved shapefiles

    Returns
    -------
    None
    """

    start_time = time.time()
    if folder is None:
        folder = settings.data_folder

    # convert directed graph G to an undirected graph for saving as a shapefile
    G_save = get_undirected(G.copy())

    # create a GeoDataFrame of the nodes and set CRS
    nodes = {node:data for node, data in G_save.nodes(data=True)}
    gdf_nodes = gpd.GeoDataFrame(nodes).T
    gdf_nodes.crs = G_save.graph['crs']

    # create a geometry column then drop the x and y columns
    gdf_nodes['geometry'] = gdf_nodes.apply(lambda row: Point(row['x'], row['y']), axis=1)
    gdf_nodes = gdf_nodes.drop(['x', 'y'], axis=1)

    # make everything but geometry column a string
    gdf_nodes['osmid'] = gdf_nodes['osmid'].astype(np.int64)
    for col in [c for c in gdf_nodes.columns if not c == 'geometry']:
        gdf_nodes[col] = gdf_nodes[col].fillna('').map(make_str)

    # create a list to hold our edges, then loop through each edge in the graph
    edges = []
    for u, v, key, data in G_save.edges(keys=True, data=True):

        # for each edge, add key and all attributes in data dict to the
        # edge_details
        edge_details = {'key':key}
        for attr_key in data:
            edge_details[attr_key] = data[attr_key]

        # if edge doesn't already have a geometry attribute, create one now
        if 'geometry' not in data:
            point_u = Point((G_save.nodes[u]['x'], G_save.nodes[u]['y']))
            point_v = Point((G_save.nodes[v]['x'], G_save.nodes[v]['y']))
            edge_details['geometry'] = LineString([point_u, point_v])

        edges.append(edge_details)

    # create a geodataframe from the list of edges and set the CRS
    gdf_edges = gpd.GeoDataFrame(edges)
    gdf_edges.crs = G_save.graph['crs']

    # make everything but geometry column a string
    for col in [c for c in gdf_edges.columns if not c == 'geometry']:
        gdf_edges[col] = gdf_edges[col].fillna('').map(make_str)

    # if the save folder does not already exist, create it with a filename
    # subfolder
    folder = os.path.join(folder, filename)
    if not os.path.exists(folder):
        os.makedirs(folder)

    # save the nodes and edges as separate ESRI shapefiles
    gdf_nodes.to_file('{}/nodes'.format(folder), encoding=encoding)
    gdf_edges.to_file('{}/edges'.format(folder), encoding=encoding)
    log('Saved graph "{}" to disk as shapefiles at "{}" in {:,.2f} seconds'.format(G_save.name, folder, time.time()-start_time))


def save_graphml(G, filename='graph.graphml', folder=None):
    """
    Save graph as GraphML file to disk.

    Parameters
    ----------
    G : networkx multidigraph
    filename : string
        the name of the graphml file (including file extension)
    folder : string
        the folder to contain the file, if None, use default data folder

    Returns
    -------
    None
    """

    start_time = time.time()
    if folder is None:
        folder = settings.data_folder

    # create a copy and convert all the node/edge attribute values to string or
    # it won't save
    G_save = G.copy()
    for dict_key in G_save.graph:
        # convert all the graph attribute values to strings
        G_save.graph[dict_key] = make_str(G_save.graph[dict_key])
    for _, data in G_save.nodes(data=True):
        for dict_key in data:
            # convert all the node attribute values to strings
            data[dict_key] = make_str(data[dict_key])
    for _, _, data in G_save.edges(keys=False, data=True):
        for dict_key in data:
            # convert all the edge attribute values to strings
            data[dict_key] = make_str(data[dict_key])

    if not os.path.exists(folder):
        os.makedirs(folder)

    nx.write_graphml(G_save, os.path.join(folder, filename))
    log('Saved graph "{}" to disk as GraphML at "{}" in {:,.2f} seconds'.format(G_save.name, os.path.join(folder, filename), time.time()-start_time))


def load_graphml(filename, folder=None):
    """
    Load a GraphML file from disk and convert the node/edge attributes to
    correct data types.

    Parameters
    ----------
    filename : string
        the name of the graphml file (including file extension)
    folder : string
        the folder containing the file, if None, use default data folder

    Returns
    -------
    networkx multidigraph
    """
    start_time = time.time()

    # read the graph from disk
    if folder is None:
        folder = settings.data_folder
    path = os.path.join(folder, filename)
    G = nx.MultiDiGraph(nx.read_graphml(path, node_type=int))

    # convert graph crs attribute from saved string to correct dict data type
    G.graph['crs'] = ast.literal_eval(G.graph['crs'])

    if 'streets_per_node' in G.graph:
        G.graph['streets_per_node'] = ast.literal_eval(G.graph['streets_per_node'])

    # convert numeric node tags from string to numeric data types
    log('Converting node and edge attribute data types')
    for _, data in G.nodes(data=True):
        data['osmid'] = int(data['osmid'])
        data['x'] = float(data['x'])
        data['y'] = float(data['y'])

    # convert numeric, bool, and list node tags from string to correct data types
    for _, _, data in G.edges(data=True, keys=False):

        # first parse oneway to bool and length to float - they should always
        # have only 1 value each
        data['oneway'] = ast.literal_eval(data['oneway'])
        data['length'] = float(data['length'])

        # these attributes might have a single value, or a list if edge's
        # topology was simplified
        for attr in ['highway', 'name', 'bridge', 'tunnel', 'lanes', 'ref', 'maxspeed', 'service', 'access', 'area', 'landuse', 'width', 'est_width']:
            # if this edge has this attribute, and it starts with '[' and ends
            # with ']', then it's a list to be parsed
            if attr in data and data[attr][0] == '[' and data[attr][-1] == ']':
                # convert the string list to a list type, else leave as
                # single-value string
                data[attr] = ast.literal_eval(data[attr])

        # osmid might have a single value or a list, but if single value, then
        # parse int
        if 'osmid' in data:
            if data['osmid'][0] == '[' and data['osmid'][-1] == ']':
                data['osmid'] = ast.literal_eval(data['osmid'])
            else:
                data['osmid'] = int(data['osmid'])

        # if geometry attribute exists, load the string as well-known text to
        # shapely LineString
        if 'geometry' in data:
            data['geometry'] = wkt.loads(data['geometry'])

    # remove node_default and edge_default metadata keys if they exist
    if 'node_default' in G.graph:
        del G.graph['node_default']
    if 'edge_default' in G.graph:
        del G.graph['edge_default']

    log('Loaded graph with {:,} nodes and {:,} edges in {:,.2f} seconds from "{}"'.format(len(list(G.nodes())),
                                                                                          len(list(G.edges())),
                                                                                          time.time()-start_time,
                                                                                          path))
    return G


def is_duplicate_edge(data, data_other):
    """
    Check if two edge data dictionaries are the same based on OSM ID and
    geometry.

    Parameters
    ----------
    data : dict
        the first edge's data
    data_other : dict
        the second edge's data

    Returns
    -------
    is_dupe : bool
    """

    is_dupe = False

    if data['osmid'] == data_other['osmid']:
        # if they have the same OSM IDs
        if ('geometry' in data) and ('geometry' in data_other):
            # if both edges have a geometry attribute
            if is_same_geometry(data, data_other):
                # if their edge geometries have the same coordinates
                is_dupe = True
        elif ('geometry' in data) and ('geometry' in data_other):
            # if neither edge has a geometry attribute
            is_dupe = True
        else:
            # if one edge has geometry attribute but the other doesn't, keep it
            pass

    return is_dupe


def is_same_geometry(data, data_other):
    """
    Check if LineString geometries in two edge data dicts are the same, in
    normal or reversed order of points.

    Parameters
    ----------
    data : dict
        the first edge's data
    data_other : dict
        the second edge's data

    Returns
    -------
    bool
    """

    # extract geometries from each edge data dict
    geom1 = [list(coords) for coords in data['geometry'].xy]
    geom2 = [list(coords) for coords in data_other['geometry'].xy]

    # reverse the first edge's list of x's and y's to look for a match in
    # either order
    geom1_r = [list(reversed(list(coords))) for coords in data['geometry'].xy]

    # if the edge's geometry matches its reverse's geometry in either order,
    # return True
    return (geom1 == geom2 or geom1_r == geom2)


def get_undirected(G):
    """
    Convert a directed graph to an undirected graph that maintains parallel
    edges if geometries differ.

    Parameters
    ----------
    G : networkx multidigraph

    Returns
    -------
    networkx multigraph
    """

    start_time = time.time()

    # set from/to nodes before making graph undirected
    G = G.copy()
    for u, v, k in G.edges(keys=True):
        G.edges[u, v, k]['from'] = u
        G.edges[u, v, k]['to'] = v

    # now convert multidigraph to a multigraph, retaining all edges in both
    # directions for now, as well as all graph attributes
    H = nx.MultiGraph()
    H.add_nodes_from(G.nodes(data=True))
    H.add_edges_from(G.edges(keys=True, data=True))
    H.graph = G.graph
    H.name = G.name

    # the previous operation added all directed edges from G as undirected
    # edges in H. this means we have duplicate edges for every bi-directional
    # street. so, look through the edges and remove any duplicates
    duplicate_edges = []
    for u, v, key, data in H.edges(keys=True, data=True):

        # if we haven't already flagged this edge as a duplicate
        if not (u, v, key) in duplicate_edges:

            # look at every other edge between u and v, one at a time
            for key_other in H[u][v]:

                # don't compare this edge to itself
                if not key_other == key:

                    # compare the first edge's data to the second's to see if
                    # they are duplicates
                    data_other = H.edges[u, v, key_other]
                    if is_duplicate_edge(data, data_other):

                        # if they match up, flag the duplicate for removal
                        duplicate_edges.append((u, v, key_other))

    H.remove_edges_from(duplicate_edges)
    log('Made undirected graph in {:,.2f} seconds'.format(time.time() - start_time))

    return H


def graph_to_gdfs(G, nodes=True, edges=True, node_geometry=True, fill_edge_geometry=True):
    """
    Convert a graph into node and/or edge GeoDataFrames

    Parameters
    ----------
    G : networkx multidigraph
    nodes : bool
        if True, convert graph nodes to a GeoDataFrame and return it
    edges : bool
        if True, convert graph edges to a GeoDataFrame and return it
    node_geometry : bool
        if True, create a geometry column from node x and y data
    fill_edge_geometry : bool
        if True, fill in missing edge geometry fields using origin and
        destination nodes

    Returns
    -------
    GeoDataFrame or tuple
        gdf_nodes or gdf_edges or both as a tuple
    """

    if not (nodes or edges):
        raise ValueError('You must request nodes or edges, or both.')

    to_return = []

    if nodes:

        start_time = time.time()

        nodes = {node:data for node, data in G.nodes(data=True)}
        gdf_nodes = gpd.GeoDataFrame(nodes).T
        if node_geometry:
            gdf_nodes['geometry'] = gdf_nodes.apply(lambda row: Point(row['x'], row['y']), axis=1)
        gdf_nodes.crs = G.graph['crs']
        gdf_nodes.gdf_name = '{}_nodes'.format(G.graph['name'])
        gdf_nodes['osmid'] = gdf_nodes['osmid'].astype(np.int64).map(make_str)

        to_return.append(gdf_nodes)
        log('Created GeoDataFrame "{}" from graph in {:,.2f} seconds'.format(gdf_nodes.gdf_name, time.time()-start_time))

    if edges:

        start_time = time.time()

        # create a list to hold our edges, then loop through each edge in the
        # graph
        edges = []
        for u, v, key, data in G.edges(keys=True, data=True):

            # for each edge, add key and all attributes in data dict to the
            # edge_details
            edge_details = {'u':u, 'v':v, 'key':key}
            for attr_key in data:
                edge_details[attr_key] = data[attr_key]

            # if edge doesn't already have a geometry attribute, create one now
            # if fill_edge_geometry==True
            if 'geometry' not in data:
                if fill_edge_geometry:
                    point_u = Point((G.nodes[u]['x'], G.nodes[u]['y']))
                    point_v = Point((G.nodes[v]['x'], G.nodes[v]['y']))
                    edge_details['geometry'] = LineString([point_u, point_v])
                else:
                    edge_details['geometry'] = np.nan

            edges.append(edge_details)

        # create a GeoDataFrame from the list of edges and set the CRS
        gdf_edges = gpd.GeoDataFrame(edges)
        gdf_edges.crs = G.graph['crs']
        gdf_edges.gdf_name = '{}_edges'.format(G.graph['name'])

        to_return.append(gdf_edges)
        log('Created GeoDataFrame "{}" from graph in {:,.2f} seconds'.format(gdf_edges.gdf_name, time.time()-start_time))

    if len(to_return) > 1:
        return tuple(to_return)
    else:
        return to_return[0]


def gdfs_to_graph(gdf_nodes, gdf_edges):
    """
    Convert node and edge GeoDataFrames into a graph

    Parameters
    ----------
    gdf_nodes : GeoDataFrame
    gdf_edges : GeoDataFrame

    Returns
    -------
    networkx multidigraph
    """

    G = nx.MultiDiGraph()
    G.graph['crs'] = gdf_nodes.crs
    G.graph['name'] = gdf_nodes.gdf_name.rstrip('_nodes')

    # add the nodes and their attributes to the graph
    G.add_nodes_from(gdf_nodes.index)
    attributes = gdf_nodes.to_dict()
    for attribute_name in gdf_nodes.columns:
        # only add this attribute to nodes which have a non-null value for it
        attribute_values = {k:v for k, v in attributes[attribute_name].items() if pd.notnull(v)}
        nx.set_node_attributes(G, name=attribute_name, values=attribute_values)

    # add the edges and attributes that are not u, v, key (as they're added
    # separately) or null
    for _, row in gdf_edges.iterrows():
        attrs = {}
        for label, value in row.iteritems():
            if (label not in ['u', 'v', 'key']) and (isinstance(value, list) or pd.notnull(value)):
                attrs[label] = value
        G.add_edge(row['u'], row['v'], key=row['key'], **attrs)

    return G


def make_shp_filename(place_name):
    """
    Create a filename string in a consistent format from a place name string.

    Parameters
    ----------
    place_name : string
        place name to convert into a filename

    Returns
    -------
    string
    """
    name_pieces = list(reversed(place_name.split(', ')))
    filename = '-'.join(name_pieces).lower().replace(' ','_')
    filename = re.sub('[^0-9a-zA-Z_-]+', '', filename)
    return filename
