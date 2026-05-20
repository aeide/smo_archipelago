from Options import FreeText, NumericOption, Toggle, DefaultOnToggle, Choice, TextChoice, Range, NamedRange, PerGameCommonOptions, DeathLink
from dataclasses import make_dataclass
from .hooks.Options import before_options_defined, after_options_defined
from .Data import category_table, game_table
from .Items import item_table


class FillerTrapPercent(Range):
    """How many fillers will be replaced with traps. 0 means no additional traps, 100 means all fillers are traps."""
    range_end = 100

meatballs_options = before_options_defined({})

# The `goal` option is defined as a static Choice class in hooks/Options.py
# (Goal). It used to be built dynamically from `victory_names` here, but the
# resulting class attribute names (e.g. `option_Metro: A Traditional Festival!`)
# weren't valid Python identifiers once a second victory location existed.

if any(item.get('trap') for item in item_table):
    meatballs_options["filler_traps"] = FillerTrapPercent

if game_table.get("death_link"):
    meatballs_options["death_link"] = DeathLink

for category in category_table:
    for option_name in category_table[category].get("yaml_option", []):
        if option_name[0] == "!":
            option_name = option_name[1:]
        if option_name not in meatballs_options:
            meatballs_options[option_name] = type(option_name, (DefaultOnToggle,), {"default": True})
            meatballs_options[option_name].__doc__ = "Should items/locations linked to this option be enabled?"

meatballs_options = after_options_defined(meatballs_options)
meatballs_options_data = make_dataclass('MeatballsOptionsClass', meatballs_options.items(), bases=(PerGameCommonOptions,))
