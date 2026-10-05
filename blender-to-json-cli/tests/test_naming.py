from blender_to_json.core.naming import parse_layer_name, parse_value, strip_numeric_suffix


def test_ignored_names():
    assert parse_layer_name('Cube') is None
    assert parse_layer_name('X | thing') is None
    assert parse_layer_name('a | b | c | d | e') is None
    assert parse_layer_name('S | ') is None


def test_categories():
    for letter, category in [('G', 'group'), ('S', 'sprite'), ('T', 'tileset'),
                             ('P', 'point'), ('Z', 'zone'), ('s', 'sprite')]:
        assert parse_layer_name(f'{letter} | thing')['category'] == category


def test_attributes_and_type():
    parsed = parse_layer_name('P | enemy_spawn | level:5, isPrivate, style: "fancy", targets:["pandas", "dogs", "Bob"]')
    assert parsed['name'] == 'enemy_spawn'
    assert 'type' not in parsed
    assert parsed['attributes'] == {
        'level': 5, 'isPrivate': True, 'style': 'fancy', 'targets': ['pandas', 'dogs', 'Bob']}

    parsed = parse_layer_name('S | props | atlas |')
    assert parsed['type'] == 'atlas'
    assert parsed['attributes'] == {}

    parsed = parse_layer_name('T | ground | jpg | lazyLoad')
    assert parsed['type'] == 'jpg'
    assert parsed['attributes'] == {'lazyLoad': True}


def test_blender_suffix_is_stripped():
    assert parse_layer_name('S | crate.001')['name'] == 'crate'
    assert parse_layer_name('S | crate | weight:10.002')['attributes'] == {'weight': 10}
    assert parse_layer_name('S | crate.001', strip_suffix=False)['name'] == 'crate.001'
    # Floats that are not exactly three decimals survive.
    assert parse_layer_name('P | p | scale:1.5')['attributes'] == {'scale': 1.5}
    assert strip_numeric_suffix('a.1234') == 'a.1234'


def test_parse_value():
    assert parse_value('true') is True
    assert parse_value('2.5') == 2.5
    assert parse_value('[1, [2, 3], "a,b"]') == [1, [2, 3], 'a,b']
    assert parse_value('{a: 1, b: "x"}') == {'a': 1, 'b': 'x'}
    assert parse_value('@difficulty') == '@difficulty'
