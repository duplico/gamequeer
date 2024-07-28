#include <stdint.h>

#include "HAL.h"
#include "gamequeer.h"
#include "grlib.h"

#include <gamequeer.h>

void gq_draw_image(
    const Graphics_Context *context, t_gq_pointer image, uint8_t width, uint8_t height, t_gq_int x, t_gq_int y) {
    uint8_t render_byte;
    int16_t bPP;
    const uint32_t palette[2] = {0, 1};
}

/// More appropriate replacement function for Graphics_drawImage.
void qc16gr_drawImage(const Graphics_Context *context, const Graphics_Image *bitmap, int16_t x, int16_t y) {
    int16_t bPP, width, height, x0, x1, x2;
    const uint32_t palette[2] = {0, 1};
    const uint8_t *image;

    //
    // Check the arguments.
    //
    assert(context);
    assert(bitmap);

    //
    // Get the image format from the image data.
    //
    bPP = bitmap->bPP;

    assert((bPP & 0x0f) == 1);

    //
    // Get the image width from the image data.
    //
    width = bitmap->xSize;

    //
    // Get the image height from the image data.
    //
    height = bitmap->ySize;

    //
    // Return without doing anything if the entire image lies outside the
    // current clipping region.
    //
    if ((x > context->clipRegion.xMax) || ((x + width - 1) < context->clipRegion.xMin) ||
        (y > context->clipRegion.yMax) || ((y + height - 1) < context->clipRegion.yMin)) {
        return;
    }

    //
    // Get the starting X offset within the image based on the current clipping
    // region.
    //
    if (x < context->clipRegion.xMin) {
        x0 = context->clipRegion.xMin - x;
    } else {
        x0 = 0;
    }

    //
    // Get the ending X offset within the image based on the current clipping
    // region.
    //
    if ((x + width - 1) > context->clipRegion.xMax) {
        x2 = context->clipRegion.xMax - x;
    } else {
        x2 = width - 1;
    }

    //
    // Reduce the height of the image, if required, based on the current
    // clipping region.
    //
    if ((y + height - 1) > context->clipRegion.yMax) {
        height = context->clipRegion.yMax - y + 1;
    }

    // Check if palette is not valid
    if (!palette) {
        return;
    }

    //
    // Get the image pixels from the image data.
    //
    image = bitmap->pPixel;

    //
    // Check if the image is not compressed.
    //
    if (!(bPP & 0xF0)) {
        //
        // The image is not compressed.  See if the top portion of the image
        // lies above the clipping region.
        //
        if (y < context->clipRegion.yMin) {
            //
            // Determine the number of rows that lie above the clipping region.
            //
            x1 = context->clipRegion.yMin - y;

            //
            // Skip past the data for the rows that lie above the clipping
            // region.
            //
            image += (((width * bPP) + 7) / 8) * x1;

            //
            // Decrement the image height by the number of skipped rows.
            //
            height -= x1;

            //
            // Increment the starting Y coordinate by the number of skipped
            // rows.
            //
            y += x1;
        }

        while (height--) {
            //
            // Draw this row of image pixels.
            //
            Graphics_drawMultiplePixelsOnDisplay(
                context->display, x + x0, y, x0 & 7, x2 - x0 + 1, bPP, image + ((x0 * bPP) / 8), palette);

            //
            // Skip past the data for this row.
            //
            image += ((width * bPP) + 7) / 8;

            //
            // Increment the Y coordinate.
            //
            y++;
        }
    } else {
        //
        // The image is compressed with RLE4, RLE7 or RLE8 Algorithm
        //

        const uint8_t *pucData = image;
        uint8_t ucRunLength, rleType;
        uint16_t uiColor;

        rleType = (bPP >> 4) & 0x0F;
        bPP &= 0x0F;

        uint16_t x_offset = 0;
        uint16_t y_offset = 0;

        do {
            if (rleType == 8) // RLE 8 bit encoding
            {
                // Read Run Length
                ucRunLength = *pucData++;
                // Read Color Pointer
                uiColor = *pucData++;
            } else if (rleType == 7) // RLE 7 bit encoding
            {
                // Read Run Length
                ucRunLength = (*pucData) >> 1;
                // Read Color Pointer
                uiColor = (*pucData++) & 0x01;
            } else // rleType = 4; RLE 4 bit encoding
            {
                // Read Run Length
                ucRunLength = (*pucData) >> 4;
                // Read Color Pointer
                uiColor = (*pucData++) & 0x0F;
            }
            uiColor = (uint16_t) palette[uiColor];

            // 0 = 1 pixel; 15 = 16, etc:
            ucRunLength++;

            while (ucRunLength--) {
                Graphics_drawPixelOnDisplay(context->display, x + x_offset, y + y_offset, uiColor);

                x_offset++;

                if (x_offset == width) {
                    x_offset = 0;
                    y_offset++;
                    if (y_offset == height) {
                        // done.
                        break;
                    }
                }
            }

        } while (y_offset < height);
    }
}
