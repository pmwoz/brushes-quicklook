import QuickLookThumbnailing

final class ThumbnailProvider: QLThumbnailProvider {
    override func provideThumbnail(
        for request: QLFileThumbnailRequest,
        _ handler: @escaping (QLThumbnailReply?, Error?) -> Void
    ) {
        let thumbnail = BrushThumbnail.load(request.fileURL, maximumSize: request.maximumSize, scale: request.scale)
        let side = min(request.maximumSize.width, request.maximumSize.height)
        let size = CGSize(width: side, height: side)
        let reply = QLThumbnailReply(contextSize: size, drawing: { context in
            // The context is sized in pixels with an identity transform, not in points.
            thumbnail.draw(in: context, size: context.boundingBoxOfClipPath.size)
            return true
        })
        handler(reply, nil)
    }
}
