import type { MMD } from '@moeru/three-mmd'
import type { AnimationClip, KeyframeTrack, SkinnedMesh } from 'three'

import { buildAnimation, MMDLoader, VMDLoader } from '@moeru/three-mmd'
import { LoadingManager, Quaternion, Vector3 } from 'three'

/** Maps in-archive relative asset paths to blob URLs for ZIP-loaded models. */
export type UrlModifier = (url: string) => string

export interface MMDLoaderContext {
  loader: MMDLoader
  manager: LoadingManager
}

/**
 * Builds an {@link MMDLoader} backed by a dedicated {@link LoadingManager}.
 *
 * MMD models reference their textures (and toon ramps) by relative paths
 * baked into the PMX/PMD binary. For ZIP imports those files live behind blob
 * URLs, so we install a URL modifier on the manager: the loader asks for
 * `tex/face.png`, the modifier rewrites it to the matching `blob:` URL. For
 * plain URL/preset models the modifier passes paths through unchanged.
 *
 * A fresh manager per load keeps URL-rewrite tables isolated between models.
 */
export function createMMDLoaderContext(urlModifier?: UrlModifier): MMDLoaderContext {
  const manager = new LoadingManager()
  if (urlModifier) {
    manager.setURLModifier((url) => {
      // NOTICE:
      // MMDLoader resolves textures by prepending the model URL's base, so for
      // ZIP imports the texture requests arrive blob-prefixed
      // (e.g. "blob:http://host/uuid/tex/face.png"). We must still run those
      // through the resolver — an earlier `blob:` short-circuit here silently
      // broke all ZIP textures. Only data: URIs (embedded toon textures) are
      // passed through untouched. The resolver falls back to the original URL
      // for the model file and any unmatched path, so this is safe.
      if (url.startsWith('data:'))
        return url
      return urlModifier(url)
    })
  }

  return { loader: new MMDLoader(manager), manager }
}

/** Loads a PMX/PMD model URL while retaining its MMD runtime. */
export function loadMMD(
  loader: MMDLoader,
  url: string,
  onProgress?: (event: ProgressEvent) => void,
): Promise<MMD> {
  return loader.loadAsync(url, onProgress)
}

/**
 * 骨架最顶层的两条"放置骨骼"：站位与朝向都会写在这里。
 * MMD 层级：全ての親 → センター → グルーブ → 腰 → …，而 足ＩＫ 挂在
 * 全ての親下面的独立分支——这正是"只转正センター会变成上身朝前、双腿劈叉"的
 * 原因：腿的 IK 目标还留在原来的坐标系里。
 */
const ALL_PARENTS_BONE = '全ての親'
const CENTER_BONE = 'センター'

interface ParsedTrack {
  track: KeyframeTrack
  bone: string
  property: 'position' | 'quaternion'
}

function parseBoneTrackName(name: string): { bone: string, property: 'position' | 'quaternion' } | undefined {
  const match = /^\.bones\[(.+)\]\.(position|quaternion)$/.exec(name)
  if (!match)
    return undefined
  return { bone: match[1], property: match[2] as 'position' | 'quaternion' }
}

function firstQuaternion(track: KeyframeTrack | undefined): Quaternion {
  if (!track || track.values.length < 4)
    return new Quaternion()
  return new Quaternion(track.values[0], track.values[1], track.values[2], track.values[3]).normalize()
}

function firstPosition(track: KeyframeTrack | undefined, fallback: Vector3): Vector3 {
  if (!track || track.values.length < 3)
    return fallback.clone()
  return new Vector3(track.values[0], track.values[1], track.values[2])
}

function isNeutralQuaternionTrack(track: KeyframeTrack): boolean {
  const values = track.values
  for (let i = 0; i + 3 < values.length; i += 4) {
    if (Math.abs(values[i]) > 1e-4 || Math.abs(values[i + 1]) > 1e-4 || Math.abs(values[i + 2]) > 1e-4)
      return false
  }
  return true
}

function isNeutralPositionTrack(track: KeyframeTrack, rest: Vector3): boolean {
  const values = track.values
  for (let i = 0; i + 2 < values.length; i += 3) {
    if (Math.abs(values[i] - rest.x) > 1e-3 || Math.abs(values[i + 1] - rest.y) > 1e-3 || Math.abs(values[i + 2] - rest.z) > 1e-3)
      return false
  }
  return true
}

/** 把整条四元数轨道左乘一个常量旋转（保留轨道内部的时间变化）。 */
function premultiplyQuaternionTrack(track: KeyframeTrack, rotation: Quaternion): void {
  const values = track.values
  const current = new Quaternion()
  const result = new Quaternion()
  for (let i = 0; i + 3 < values.length; i += 4) {
    current.set(values[i], values[i + 1], values[i + 2], values[i + 3])
    result.copy(rotation).multiply(current)
    values[i] = result.x
    values[i + 1] = result.y
    values[i + 2] = result.z
    values[i + 3] = result.w
  }
}

/** 位移轨道：先绕原点旋转再平移（刚体变换）。 */
function transformPositionTrack(track: KeyframeTrack, rotation: Quaternion, translation: Vector3): void {
  const values = track.values
  const point = new Vector3()
  for (let i = 0; i + 2 < values.length; i += 3) {
    point.set(values[i], values[i + 1], values[i + 2]).applyQuaternion(rotation).add(translation)
    values[i] = point.x
    values[i + 1] = point.y
    values[i + 2] = point.z
  }
}

function resetQuaternionTrack(track: KeyframeTrack): void {
  const values = track.values
  for (let i = 0; i + 3 < values.length; i += 4) {
    values[i] = 0
    values[i + 1] = 0
    values[i + 2] = 0
    values[i + 3] = 1
  }
}

function resetPositionTrack(track: KeyframeTrack, rest: Vector3): void {
  const values = track.values
  for (let i = 0; i + 2 < values.length; i += 3) {
    values[i] = rest.x
    values[i + 1] = rest.y
    values[i + 2] = rest.z
  }
}

/** 上半身链：用于判断"身体实际朝向"（个别动作把朝向拆开写在根骨骼与身体上）。 */
const BODY_CHAIN = [ALL_PARENTS_BONE, CENTER_BONE, 'グルーブ', '腰', '上半身', '上半身2']
/** 身体与根骨骼朝向差超过该角度时，以身体朝向为基准修正。 */
const BODY_YAW_GAP_LIMIT = Math.PI / 4

function yawOf(rotation: Quaternion): number {
  return 2 * Math.atan2(rotation.y, rotation.w)
}

function wrapAngle(radians: number): number {
  return Math.atan2(Math.sin(radians), Math.cos(radians))
}

function composedFirstQuaternion(entries: ParsedTrack[], bones: string[]): Quaternion {
  const result = new Quaternion()
  for (const bone of bones) {
    const track = entries.find(entry => entry.bone === bone && entry.property === 'quaternion')?.track
    if (track)
      result.multiply(firstQuaternion(track))
  }
  return result
}

/**
 * 根骨骼"首帧归一化"（原地化 + 转向正前方）。
 *
 * 许多配布动作（尤其「背景キャラ用」对谈动作）会把站位与朝向焊死在首帧上——
 * 例如 `センター` x=±8、偏航 ±91°。这里计算首帧整套骨架的"放置变换"，然后把
 * 它的逆**逐顶层分支烘焙**进动作数据：
 *   - 身体分支（センター）与各条独立顶层分支（左右足ＩＫ 等）都做同样的
 *     刚体反向旋转/平移，所以上身和腿始终一致（不会出现只转上身、双腿劈叉）；
 *   - 姿势内部的骨头一根都不改，动作本身的点头/晃动/前倾全部保留；
 *   - 修正之后每个动作的根骨骼都是中性的——**关键**：动作之间交叉淡入淡出时
 *     不会再混合"90° 的根旋转"和"零位"，因此不会绕着原点滑行半圈。
 *
 * 朝向基准优先用根骨骼；个别文件把朝向"拆开写"（根骨骼 -91°、身体又反向拧
 * 回 +115°，身体实际朝向 +24°），此时以身体链的实际朝向为基准，否则修正后
 * 反而会侧脸。两者相差很小时维持根骨骼基准，不影响其它动作。
 */
export function normalizeRootMotionInPlace(clip: AnimationClip, mesh: SkinnedMesh): void {
  const skeleton = new Map(mesh.skeleton.bones.map(bone => [bone.name, bone]))
  const restOf = (name: string) => skeleton.get(name)?.position ?? new Vector3()

  const entries: ParsedTrack[] = []
  for (const track of clip.tracks) {
    const parsed = parseBoneTrackName(track.name)
    if (parsed)
      entries.push({ track, ...parsed })
  }
  if (!entries.length)
    return

  const animated = new Set<string>()
  for (const entry of entries) {
    const neutral = entry.property === 'quaternion'
      ? isNeutralQuaternionTrack(entry.track)
      : isNeutralPositionTrack(entry.track, restOf(entry.bone))
    if (!neutral)
      animated.add(entry.bone)
  }

  // "放置承载骨骼"：没有任何非中性动画祖先、直通 全ての親 的顶层分支。
  // 身体（センター）算一条，左右足ＩＫ 等独立分支各算一条。
  const carriers = new Set<string>()
  for (const bone of animated) {
    if (bone === ALL_PARENTS_BONE)
      continue
    let node = skeleton.get(bone)?.parent
    let topLevel = false
    while (node) {
      if (node.name === ALL_PARENTS_BONE) {
        topLevel = true
        break
      }
      if (animated.has(node.name))
        break
      node = node.parent
    }
    if (topLevel)
      carriers.add(bone)
  }

  const allParentsTracks = entries.filter(entry => entry.bone === ALL_PARENTS_BONE)
  const centerQuatTrack = entries.find(entry => entry.bone === CENTER_BONE && entry.property === 'quaternion')?.track
  const centerPosTrack = entries.find(entry => entry.bone === CENTER_BONE && entry.property === 'position')?.track
  const allParentsQuatTrack = allParentsTracks.find(entry => entry.property === 'quaternion')?.track
  const allParentsPosTrack = allParentsTracks.find(entry => entry.property === 'position')?.track

  if (!carriers.size && !animated.has(ALL_PARENTS_BONE))
    return

  // 首帧朝向：根骨骼基准 = 全ての親 × センター；身体基准 = 上半身链的实际朝向。
  const allParentsQuat0 = firstQuaternion(allParentsQuatTrack)
  const centerRotation = allParentsQuat0.clone().multiply(firstQuaternion(centerQuatTrack))
  const centerYaw = yawOf(centerRotation)
  const bodyYaw = yawOf(composedFirstQuaternion(entries, BODY_CHAIN))
  const referenceYaw = Math.abs(wrapAngle(bodyYaw - centerYaw)) > BODY_YAW_GAP_LIMIT ? bodyYaw : centerYaw
  const rotation = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), -referenceYaw)

  // 首帧 センター 相对模型默认位姿的世界位移，旋进修正后的坐标系再取反。
  const restAllParents = restOf(ALL_PARENTS_BONE)
  const restCenter = restOf(CENTER_BONE)
  const translation = firstPosition(allParentsPosTrack, restAllParents)
    .add(firstPosition(centerPosTrack, restCenter).applyQuaternion(allParentsQuat0))
    .sub(restAllParents.clone().add(restCenter))
    .applyQuaternion(rotation)
    .multiplyScalar(-1)
  // 只取消横向/纵深常量，保留作者写的高度常量与全部相对晃动。
  translation.y = 0

  // 修正逐顶层分支下发；根骨骼保持中性（跨动作混合不再转圈）。
  for (const entry of carriers) {
    for (const trackEntry of entries) {
      if (trackEntry.bone !== entry)
        continue
      if (trackEntry.property === 'quaternion')
        premultiplyQuaternionTrack(trackEntry.track, rotation)
      else
        transformPositionTrack(trackEntry.track, rotation, translation)
    }
  }

  // 极少见：動作把放置直接写在 全ての親 上——并入上面的修正后清成中性。
  if (animated.has(ALL_PARENTS_BONE)) {
    for (const entry of allParentsTracks) {
      if (entry.property === 'quaternion')
        resetQuaternionTrack(entry.track)
      else
        resetPositionTrack(entry.track, restAllParents)
    }
  }
}

export interface LoadAnimationOptions {
  /**
   * 是否归一化根骨骼位移/朝向（默认 true）。默认让「背景角色用」对谈动作不再
   * 跑到侧边或转身；需要保留原始走位的动作（如舞蹈）可传 false。
   */
  normalizeRootMotion?: boolean
}

/**
 * Parses a VMD model motion and binds its bone and morph tracks to `mesh`.
 * AIRI intentionally does not consume camera motion from this adapter.
 */
export async function loadMMDAnimationClip(
  url: string,
  mesh: SkinnedMesh,
  onProgress?: (event: ProgressEvent) => void,
  options?: LoadAnimationOptions,
): Promise<AnimationClip> {
  const vmd = await new VMDLoader().loadAsync(url, onProgress)
  const clip = buildAnimation(vmd, mesh)
  if (options?.normalizeRootMotion !== false)
    normalizeRootMotionInPlace(clip, mesh)
  return clip
}
