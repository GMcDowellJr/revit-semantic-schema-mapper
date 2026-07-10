// Copyright (c) Lookup Foundation and Contributors
// 
// Permission to use, copy, modify, and distribute this software in
// object code form for any purpose and without fee is hereby granted,
// provided that the above copyright notice appears in all copies and
// that both that copyright notice and the limited warranty and
// restricted rights notice below appear in all supporting
// documentation.
// 
// THIS PROGRAM IS PROVIDED "AS IS" AND WITH ALL FAULTS.
// NO IMPLIED WARRANTY OF MERCHANTABILITY OR FITNESS FOR A PARTICULAR USE IS PROVIDED.
// THERE IS NO GUARANTEE THAT THE OPERATION OF THE PROGRAM WILL BE
// UNINTERRUPTED OR ERROR FREE.

using LookupEngine.Abstractions.Configuration;
using LookupEngine.Abstractions.Decomposition;
using RevitLookup.Common.Utils;
using Color = System.Windows.Media.Color;

namespace RevitLookup.Core.Decomposition.Descriptors;

public sealed class ColorMediaDescriptor : Descriptor, IDescriptorExtension
{
    private readonly Color _color;

    public ColorMediaDescriptor(Color color)
    {
        _color = color;
        Name = $"RGB: {color.R} {color.G} {color.B}";
    }

    public void RegisterExtensions(IExtensionManager manager)
    {
        manager.Register("HEX", () => Variants.Value(ColorRepresentationUtils.ColorToHex(_color.GetDrawingColor())));
        manager.Register("HEX int", () => Variants.Value(ColorRepresentationUtils.ColorToHexInteger(_color.GetDrawingColor())));
        manager.Register("RGB", () => Variants.Value(ColorRepresentationUtils.ColorToRgb(_color.GetDrawingColor())));
        manager.Register("HSL", () => Variants.Value(ColorRepresentationUtils.ColorToHsl(_color.GetDrawingColor())));
        manager.Register("HSV", () => Variants.Value(ColorRepresentationUtils.ColorToHsv(_color.GetDrawingColor())));
        manager.Register("CMYK", () => Variants.Value(ColorRepresentationUtils.ColorToCmyk(_color.GetDrawingColor())));
        manager.Register("HSB", () => Variants.Value(ColorRepresentationUtils.ColorToHsb(_color.GetDrawingColor())));
        manager.Register("HSI", () => Variants.Value(ColorRepresentationUtils.ColorToHsi(_color.GetDrawingColor())));
        manager.Register("HWB", () => Variants.Value(ColorRepresentationUtils.ColorToHwb(_color.GetDrawingColor())));
        manager.Register("NCol", () => Variants.Value(ColorRepresentationUtils.ColorToNCol(_color.GetDrawingColor())));
        manager.Register("CIELAB", () => Variants.Value(ColorRepresentationUtils.ColorToCielab(_color.GetDrawingColor())));
        manager.Register("CIEXYZ", () => Variants.Value(ColorRepresentationUtils.ColorToCieXyz(_color.GetDrawingColor())));
        manager.Register("VEC4", () => Variants.Value(ColorRepresentationUtils.ColorToFloat(_color.GetDrawingColor())));
        manager.Register("Decimal", () => Variants.Value(ColorRepresentationUtils.ColorToDecimal(_color.GetDrawingColor())));
        manager.Register("Name", () => Variants.Value(ColorRepresentationUtils.GetColorName(_color.GetDrawingColor())));
    }
}