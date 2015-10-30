"""Compile/Translate Yahoo Pipe into Python

    Takes a JSON representation of a Yahoo pipe and either:
     a) translates it into a Python script containing a function
        (using generators to build the pipeline) or
     b) compiles it as a pipeline of generators which can be executed
        in-process

    Usage:
     a) python pipe2py/compile.py tests/pipelines/testpipe1.json
        python pipe2py/pypipelines/testpipe1.py

     b) from pipe2py import compile, Context

        pipe_def = json.loads(pjson)
        pipe = parse_pipe_def(pipe_def, pipe_name)
        pipeline = build_pipeline(Context(), pipe)
        print list(pipeline)

    Instead of passing a filename, a pipe id can be passed (-p) to fetch the
    JSON from Yahoo, e.g.

        python compile.py -p 2de0e4517ed76082dcddf66f7b218057

    Author: Greg Gaughan
    Idea: Tony Hirst (http://ouseful.wordpress.com/2010/02/25/
        starting-to-think-about-a-yahoo-pipes-code-generator)
    Python generator pipelines inspired by:
        David Beazely (http://www.dabeaz.com/generators-uk)
    auto-rss module by Mark Pilgrim

   License: see LICENSE file
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from json import dumps, JSONEncoder
from codecs import open
from itertools import chain, izip
from collections import defaultdict
from importlib import import_module
from pprint import PrettyPrinter
from jinja2 import Environment, PackageLoader
from pipe2py.modules.pipeforever import pipe_forever
from pipe2py.lib import utils
from pipe2py.lib.pprint2 import Id, repr_args, str_args
from pipe2py.lib.topsort import topological_sort


class MyPrettyPrinter(PrettyPrinter):
    def format(self, object, context, maxlevels, level):
        if isinstance(object, unicode):
            return (object.encode('utf8'), True, False)
        else:
            return PrettyPrinter.format(
                self, object, context, maxlevels, level)


class CustomEncoder(JSONEncoder):
    def default(self, obj):
        if set(['quantize', 'year', 'tm_hour']).intersection(dir(obj)):
            return str(obj)
        elif set(['next', 'union']).intersection(dir(obj)):
            return list(obj)

        return JSONEncoder.default(self, obj)


def write_file(data, path, pretty=False):
    if data and path:
        with open(path, 'w', encoding='utf-8') as f:
            if hasattr(data, 'keys') and pretty:
                kwargs = {
                    'cls': CustomEncoder,
                    'sort_keys': True,
                    'indent': 4,
                    'ensure_ascii': False
                }

                data = dumps(data, **kwargs)
            elif hasattr(data, 'keys'):
                data = dumps(data, ensure_ascii=False)
            elif pretty:
                data = unicode(MyPrettyPrinter().pformat(data), 'utf-8')

            return f.write(data)


def _get_zipped(context, pipe, **kwargs):
    module_ids = kwargs['module_ids']
    module_names = kwargs['module_names']
    pipe_names = kwargs['pipe_names']
    return izip(module_ids, module_names, pipe_names)


def _gen_string_modules(context, pipe, zipped):
    for module_id, module_name, pipe_name in zipped:
        pyargs = _get_pyargs(context, pipe, module_id)
        pykwargs = dict(_gen_pykwargs(context, pipe, module_id))

        if context and context.verbose:
            con_args = filter(lambda x: x != Id('context'), pyargs)
            nconf_kwargs = filter(lambda x: x[0] != 'conf', pykwargs.items())
            conf_kwargs = filter(lambda x: x[0] == 'conf', pykwargs.items())
            all_args = chain(con_args, nconf_kwargs, conf_kwargs)

            print (
                '%s = %s(%s)' % (
                    module_id, pipe_name, str_args(all_args)
                )
            ).encode('utf-8')

        yield {
            'args': repr_args(chain(pyargs, pykwargs.items())),
            'id': module_id,
            'sub_pipe': module_name.startswith('pipe_'),
            'name': module_name,
            'pipe_name': pipe_name,
        }


def _gen_steps(context, pipe, **kwargs):
    module_id = kwargs['module_id']
    module_name = kwargs['module_name']
    pipe_name = kwargs['pipe_name']
    steps = kwargs['steps']

    if module_name.startswith('pipe_'):
        # Import any required sub-pipelines and user inputs
        # Note: assumes they have already been compiled to accessible .py
        # files
        import_name = 'pipe2py.pypipelines.%s' % module_name
    else:
        import_name = 'pipe2py.modules.%s' % module_name

    module = import_module(import_name)
    pipe_generator = getattr(module, pipe_name)

    # if this module is an embedded module:
    if module_id in pipe['embed']:
        # We need to wrap submodules (used by loops) so we can pass the
        # input at runtime (as we can to sub-pipelines)
        # Note: no embed (so no subloops) or wire pykwargs are passed
        pipe_generator.__name__ = str('pipe_%s' % module_id)
        yield (module_id, pipe_generator)
    else:  # else this module is not embedded:
        pyargs = _get_pyargs(context, pipe, module_id, steps)
        pykwargs = dict(_gen_pykwargs(context, pipe, module_id, steps))
        yield (module_id, pipe_generator(*pyargs, **pykwargs))


def _get_steps(context, pipe, zipped):
    steps = {'forever': pipe_forever()}

    for module_id, module_name, pipe_name in zipped:
        kwargs = {
            'module_id': module_id,
            'module_name': module_name,
            'pipe_name': pipe_name,
            'steps': steps,
        }

        steps.update(dict(_gen_steps(context, pipe, **kwargs)))

    return steps


def _get_pyargs(context, pipe, module_id, steps=None):
    describe = context.describe_input or context.describe_dependencies

    if not (describe and steps):
        # find the default input of this module
        input_module = _get_input_module(pipe, module_id, steps)

        return [context, input_module] if steps else [
            Id('context'), Id(input_module)]


def _gen_pykwargs(context, pipe, module_id, steps=None):
    module = pipe['modules'][module_id]
    yield ('conf', module['conf'])
    describe = context.describe_input or context.describe_dependencies

    if not (describe and steps):
        wires = pipe['wires']
        module_type = module['type']

        # find the default input of this module
        for key, pipe_wire in wires.items():
            moduleid = utils.pythonise(pipe_wire['src']['moduleid'])

            # todo? this equates the outputs
            is_default_out_only = (
                utils.pythonise(pipe_wire['tgt']['moduleid']) == module_id
                and pipe_wire['tgt']['id'] != '_INPUT'
                and pipe_wire['src']['id'].startswith('_OUTPUT')
            )

            # if the wire is to this module and it's *NOT* the default input
            # but it *is* the default output
            if is_default_out_only:
                # set the extra inputs of this module as pykwargs of this module
                pipe_id = utils.pythonise(pipe_wire['tgt']['id'])
                yield (pipe_id, steps[moduleid] if steps else Id(moduleid))

        # set the embedded module in the pykwargs if this is loop module
        if module_type == 'loop':
            value = module['conf']['embed']['value']
            pipe_id = utils.pythonise(value['id'])
            updated = steps[pipe_id] if steps else Id('pipe_%s' % pipe_id)
            yield ('embed', updated)

        # set splits in the pykwargs if this is split module
        def filter_func(x):
            module_id == utils.pythonise(x[1]['src']['moduleid'])

        if module_type == 'split':
            filtered = filter(filter_func, pipe['wires'].items())
            count = len(filtered)
            updated = count if steps else Id(count)
            yield ('splits', updated)


def _get_input_module(pipe, module_id, steps):
    input_module = steps['forever'] if steps else 'forever'

    if module_id in pipe['embed']:
        input_module = '_INPUT'
    else:
        for key, pipe_wire in pipe['wires'].items():
            moduleid = utils.pythonise(pipe_wire['src']['moduleid'])

            # todo? this equates the outputs
            is_default_in_and_out = (
                utils.pythonise(pipe_wire['tgt']['moduleid']) == module_id
                and pipe_wire['tgt']['id'] == '_INPUT'
                and pipe_wire['src']['id'].startswith('_OUTPUT')
            )

            # if the wire is to this module and it's the default input and it's
            # the default output:
            if is_default_in_and_out:
                input_module = steps[moduleid] if steps else moduleid
                break

    return input_module


def parse_pipe_def(pipe_def, pipe_name='anonymous'):
    """Parse pipe JSON into internal structures

    Parameters
    ----------
    pipe_def -- JSON representation of the pipe
    pipe_name -- a name for the pipe (used for linking pipes)

    Returns:
    pipe -- an internal representation of a pipe
    """
    graph = defaultdict(list, utils.gen_graph1(pipe_def))
    [graph[k].append(v) for k, v in utils.gen_graph2(pipe_def)]
    modules = dict(utils.gen_modules(pipe_def))
    embed = dict(utils.gen_embedded_modules(pipe_def))
    modules.update(embed)

    return {
        'name': utils.pythonise(pipe_name),
        'modules': modules,
        'embed': embed,
        'graph': dict(utils.gen_graph3(graph)),
        'wires': dict(utils.gen_wires(pipe_def)),
    }


def build_pipeline(context, pipe, pipe_def):
    """Convert a pipe into an executable Python pipeline

        If context.describe_input or context.describe_dependencies then just
        return that instead of the pipeline

        Note: any subpipes must be available to import from pipe2py.pypipelines
    """
    module_ids = topological_sort(pipe['graph'])
    pydeps = utils.extract_dependencies(pipe_def)
    pyinput = utils.extract_input(pipe_def)

    if not (context.describe_input or context.describe_dependencies):
        kwargs = {
            'module_ids': module_ids,
            'module_names': utils.gen_names(module_ids, pipe),
            'pipe_names': utils.gen_names(module_ids, pipe, 'pipe'),
        }

        zipped = _get_zipped(context, pipe, **kwargs)
        steps = _get_steps(context, pipe, zipped)

    if context.describe_input and context.describe_dependencies:
        pipeline = [{'inputs': pyinput, 'dependencies': pydeps}]
    elif context.describe_input:
        pipeline = pyinput
    elif context.describe_dependencies:
        pipeline = pydeps
    else:
        pipeline = steps[module_ids[-1]]

    for i in pipeline:
        yield i


def stringify_pipe(context, pipe, pipe_def):
    """Convert a pipe into Python script
    """
    module_ids = topological_sort(pipe['graph'])

    kwargs = {
        'module_ids': module_ids,
        'module_names': utils.gen_names(module_ids, pipe),
        'pipe_names': utils.gen_names(module_ids, pipe, 'pipe'),
    }

    zipped = _get_zipped(context, pipe, **kwargs)
    modules = list(_gen_string_modules(context, pipe, zipped))
    pydeps = utils.extract_dependencies(pipe_def)
    pyinput = utils.extract_input(pipe_def)
    env = Environment(loader=PackageLoader('pipe2py'))
    template = env.get_template('pypipe.txt')

    tmpl_kwargs = {
        'modules': modules,
        'pipe_name': pipe['name'],
        'inputs': unicode(pyinput),
        'dependencies': unicode(pydeps),
        'embedded_pipes': pipe['embed'],
        'last_module': module_ids[-1],
    }

    return template.render(**tmpl_kwargs)
