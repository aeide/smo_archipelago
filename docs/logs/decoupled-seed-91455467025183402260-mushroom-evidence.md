# Evidence extract — decoupled seed 91455467025183402260, Mushroom overworld falsely in sphere 1

Extracted 2026-07-17 from `AP_29401164300836747916_Spoiler.txt` (Devon's first completed
decoupled seed; full spoiler in Devon's AP output folder). Devon's in-game report: **he
never arrived in the Mushroom Kingdom overworld the entire run** and found no route to it
in the spoiler — yet logic placed MK overworld moons in sphere 1.

## Seed settings (relevant subset)

```
Archipelago Version 0.6.7  -  Seed: 91455467025183402260
Filling Algorithm:               balanced
Accessibility:                   Minimal
Goal:                            Mushroom Kingdom
Entrance Shuffle:                Decoupled
Capturesanity:                   Yes
Abilitysanity:                   Yes
Randomize Kingdom Moon Gates:    Yes
Multi-Moon Shuffle:              Yes
Location Count:                  775
```

## Every shuffled connection touching Mushroom Kingdom

Doors IN MK overworld (all lead OUT — irrelevant to arrival):

```
[Mushroom Kingdom] "Castle Courtyard 64" door (marker 'CostumeEventWorldPeach') <-> "Wintery Flower Road" exit (Snow)
[Mushroom Kingdom] "Picture Match (Mario)" door (marker 'Fukuwarai2') <-> "2D Cube" exit (Cloud)
[Mushroom Kingdom] "Yoshi in the Sea of Clouds" door (marker 'PeachWorldEx1a') <-> "Dashing Over Cold Water" exit (Snow)
[Mushroom Kingdom] "8-Bit Bullet Bills" door (marker 'PeachWorldEx2a') <-> "Crazy Cap Store (Luncheon)" exit (Luncheon)
[Mushroom Kingdom] "Crazy Cap Store (Mushroom)" door (marker 'PeachWorldShopA') <-> "Push Block Peril" exit (Cap)
```

Rows landing in MK — ALL five are subarea INTERIORS, never the overworld:

```
[Sand Kingdom]    "Ice Cave" door (marker 'arijigoku2')                    <-> "8-Bit Bullet Bills" exit (Mushroom, 'PeachWorldEx2a')
[Seaside Kingdom] "Spinning Maze" door (marker 'SeaWorldMoonEX2')          <-> "Crazy Cap Store (Mushroom)" exit (Mushroom, 'PeachWorldShopA')
[Seaside Kingdom] "Stretching Up the Sinking Island" door ('SeaWorldEX3b') <-> "Yoshi in the Sea of Clouds" exit (Mushroom, 'PeachWorldEx1a')
[Wooded Kingdom]  "Breakdown Road" door (marker 'KillerRoad')              <-> "Castle Courtyard 64" exit (Mushroom, 'CostumeEventWorldPeach')
[Wooded Kingdom]  "Costume Room (Wooded)" door (marker 'Explorer_Bonus')   <-> "Picture Match (Mario)" exit (Mushroom, 'Fukuwarai2')
```

There is NO row whose destination is the MK overworld. In decoupled mode, subarea exits
pop back to the door of origin (P7: both exit classes collapse to origin), so entering a
MK subarea from Sand/Seaside/Wooded never puts Mario in MK overworld.

## Yet sphere 1 contains MK OVERWORLD moons (not subarea moons)

```
1: {
  Cap: Frog-Jumping from the Top Deck  |  Cascade: Behind the Waterfall  |  Luncheon: Corner of the Magma Swamp
  Mushroom: Found at Peach's Castle! Good Dog!
  Mushroom: Found with Mushroom Kingdom Art
  Mushroom: Gardening for Toad: Field Seed
  Mushroom: Gardening for Toad: Pasture Seed
  Mushroom: Gobbling Fruit with Yoshi
  Mushroom: Grow a Flower Garden
  Mushroom: Hat-and-Seek: Mushroom Kingdom
  Mushroom: Loose-Tile Trackdown
  Mushroom: Love at Peach's Castle
  Mushroom: Mushroom Kingdom Regular Cup
  Mushroom: Mushroom Kingdom Timer Challenge
  Mushroom: Pops Out of the Tail
  Mushroom: Yoshi's All Filled Up!
}
```

Several hold progression (Lava Bubble, Cap Bounce, Power Moons) — fill trusted the
false reachability.

The subarea moons (Secret 2D Treasure, Shopping Near Peach's Castle, Yoshi's Feast…)
are correctly attributed to their shuffled origins elsewhere in the log — the bug is
specifically the OVERWORLD region.

## Victory is correctly last (sphere 21) — so the gate on victory ≠ the gate on the region's moons

```
21: {
  Arrive in the Mushroom Kingdom: __Victory__
}
```

## Unreachable Progression Items (Accessibility: Minimal tolerated these)

```
Parabones:               Cap: Slipping Through the Poison Tide
Progressive Ground Pound: Lake: Bird Traveling Over the Lake
Tree:                    Luncheon: The Treasure Chest in the Veggies
Up Throw:                Wooded: Bird Traveling the Forest
```
