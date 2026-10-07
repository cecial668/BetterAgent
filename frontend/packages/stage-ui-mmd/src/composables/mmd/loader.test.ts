import type { AnimationClip, KeyframeTrack, SkinnedMesh } from 'three'

import { describe, expect, it } from 'vitest'
import { AnimationClip as Clip, Quaternion, QuaternionKeyframeTrack, Vector3, VectorKeyframeTrack } from 'three'

import { normalizeRootMotionInPlace } from './loader'

/**
 * 假模型：全ての親(根) → センター(身体)，以及挂在根下的左右足ＩＫ。
 * 与真实 MMD 层级一致：腿的 IK 目标不在 センター 子树里。
 */
function fakeMesh(): SkinnedMesh {
  const allParents: any = { name: '全ての親', position: new Vector3(0, 0, 0), parent: null }
  const center: any = { name: 'センター', position: new Vector3(0, 8, 0), parent: allParents }
  const leftIk: any = { name: '左足ＩＫ', position: new Vector3(-2, 0, 0), parent: allParents }
  const rightIk: any = { name: '右足ＩＫ', position: new Vector3(2, 0, 0), parent: allParents }
  const bones = [allParents, center, leftIk, rightIk]
  return {
    skeleton: {
      bones,
      getBoneByName: (name: string) => bones.find(bone => bone.name === name),
    },
  } as unknown as SkinnedMesh
}

function findTrack(clip: AnimationClip, name: string): KeyframeTrack | undefined {
  return clip.tracks.find(track => track.name === name)
}

function quatAt(track: KeyframeTrack, index: number): Quaternion {
  return new Quaternion(
    track.values[index * 4],
    track.values[index * 4 + 1],
    track.values[index * 4 + 2],
    track.values[index * 4 + 3],
  )
}

function vecAt(track: KeyframeTrack, index: number): Vector3 {
  return new Vector3(
    track.values[index * 3],
    track.values[index * 3 + 1],
    track.values[index * 3 + 2],
  )
}

/** 模拟「背景キャラ用」对谈动作：整个人平移 -8、绕 Y +90°，IK 目标与身体一致。 */
function buildAuthoredMotion(): AnimationClip {
  const bodyYaw = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), Math.PI / 2)
  const swayYaw = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), Math.PI / 2 + 0.1)
  const lateral = new Vector3(-8, 0, 0)
  const rotatedLeft = new Vector3(-2, 0, 0).applyQuaternion(bodyYaw)
  const rotatedRight = new Vector3(2, 0, 0).applyQuaternion(bodyYaw)

  return new Clip('', -1, [
    // 根骨骼在真实文件里是 1 帧中性轨道
    new QuaternionKeyframeTrack('.bones[全ての親].quaternion', [0], [0, 0, 0, 1]),
    new VectorKeyframeTrack('.bones[全ての親].position', [0], [0, 0, 0]),
    new VectorKeyframeTrack(
      '.bones[センター].position',
      [0, 1],
      [
        lateral.x, 7.5, lateral.z,
        -7.6, 8.2, -0.3,
      ],
    ),
    new QuaternionKeyframeTrack(
      '.bones[センター].quaternion',
      [0, 1],
      [bodyYaw.x, bodyYaw.y, bodyYaw.z, bodyYaw.w, swayYaw.x, swayYaw.y, swayYaw.z, swayYaw.w],
    ),
    new VectorKeyframeTrack(
      '.bones[左足ＩＫ].position',
      [0, 1],
      [
        lateral.x + rotatedLeft.x, rotatedLeft.y, lateral.z + rotatedLeft.z,
        lateral.x + rotatedLeft.x + 0.1, rotatedLeft.y, lateral.z + rotatedLeft.z - 0.2,
      ],
    ),
    new VectorKeyframeTrack(
      '.bones[右足ＩＫ].position',
      [0, 1],
      [
        lateral.x + rotatedRight.x, rotatedRight.y, lateral.z + rotatedRight.z,
        lateral.x + rotatedRight.x, rotatedRight.y + 0.1, lateral.z + rotatedRight.z,
      ],
    ),
  ])
}

describe('normalizeRootMotionInPlace', () => {
  it('身体与腿一起转回正前方，根骨骼保持中性（跨动作混合不再转圈）', () => {
    const clip = buildAuthoredMotion()
    const before = clip.tracks.length

    normalizeRootMotionInPlace(clip, fakeMesh())

    // 不新增根骨骼轨道：修正被下发给各顶层分支
    expect(clip.tracks).toHaveLength(before)

    // 身体首帧：朝向正前、位置回到默认（保留高度 7.5），不再是侧站 8 单位外
    const centerPos = findTrack(clip, '.bones[センター].position')!
    const centerQuat = findTrack(clip, '.bones[センター].quaternion')!
    const body0 = quatAt(centerQuat, 0)
    expect(Math.abs(body0.x) + Math.abs(body0.y) + Math.abs(body0.z)).toBeLessThan(1e-5)
    expect(body0.w).toBeCloseTo(1, 5)
    const center0 = vecAt(centerPos, 0)
    expect(center0.x).toBeCloseTo(0, 5)
    expect(center0.z).toBeCloseTo(0, 5)
    expect(center0.y).toBeCloseTo(7.5, 5)

    // 腿的 IK 目标同样回到正面默认位置（相对身体保持一致，不会劈叉）
    const left0 = vecAt(findTrack(clip, '.bones[左足ＩＫ].position')!, 0)
    const right0 = vecAt(findTrack(clip, '.bones[右足ＩＫ].position')!, 0)
    expect(left0.x).toBeCloseTo(-2, 5)
    expect(left0.z).toBeCloseTo(0, 5)
    expect(right0.x).toBeCloseTo(2, 5)
    expect(right0.z).toBeCloseTo(0, 5)

    // 根骨骼仍是中性（这就是"不再滑行半圈"的根因修复）
    const apQuat = findTrack(clip, '.bones[全ての親].quaternion')!
    expect(quatAt(apQuat, 0).w).toBeCloseTo(1, 5)

    // 相对晃动保留：身体末帧相对首帧的偏移 = 原始相对偏移 × 修正旋转
    const correction = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), -Math.PI / 2)
    const expectedDelta = new Vector3(0.4, 0.7, -0.3).applyQuaternion(correction)
    const center1 = vecAt(centerPos, 1)
    expect(center1.x - center0.x).toBeCloseTo(expectedDelta.x, 4)
    expect(center1.y - center0.y).toBeCloseTo(expectedDelta.y, 4)
    expect(center1.z - center0.z).toBeCloseTo(expectedDelta.z, 4)
  })

  it('朝向被拆分写在根骨骼与身体上时，以身体实际朝向为基准（不会修成侧脸）', () => {
    // 模拟 xs-talk4：センター -90°，上半身又反向 +90°（身体实际朝前）
    const centerYaw = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), -Math.PI / 2)
    const upperCounter = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), Math.PI / 2)
    const clip = new Clip('', -1, [
      new VectorKeyframeTrack('.bones[センター].position', [0], [-8, 8, 0]),
      new QuaternionKeyframeTrack(
        '.bones[センター].quaternion', [0], [centerYaw.x, centerYaw.y, centerYaw.z, centerYaw.w],
      ),
      new QuaternionKeyframeTrack(
        '.bones[上半身].quaternion', [0], [upperCounter.x, upperCounter.y, upperCounter.z, upperCounter.w],
      ),
    ])

    normalizeRootMotionInPlace(clip, fakeMesh())

    // 身体链的净朝向必须保持朝前，而不是被根骨骼基准修成 ±90° 侧脸
    const net = quatAt(findTrack(clip, '.bones[センター].quaternion')!, 0)
      .multiply(quatAt(findTrack(clip, '.bones[上半身].quaternion')!, 0))
    const yaw = 2 * Math.atan2(net.y, net.w)
    expect(Math.abs(yaw)).toBeLessThan(1e-3)

    // 侧移照常回收
    const centerPos = vecAt(findTrack(clip, '.bones[センター].position')!, 0)
    expect(centerPos.x).toBeCloseTo(0, 5)
    expect(centerPos.z).toBeCloseTo(0, 5)
  })

  it('身体内部骨骼（在有动画的中轴之下）不受影响', () => {
    const upperTrack = new QuaternionKeyframeTrack(
      '.bones[上半身].quaternion', [0], [0, 0.1, 0, 0.995],
    )
    const clip = new Clip('', -1, [
      new VectorKeyframeTrack('.bones[センター].position', [0], [-8, 8, 0]),
      upperTrack,
    ])

    normalizeRootMotionInPlace(clip, fakeMesh())

    expect(upperTrack.values[1]).toBeCloseTo(0.1, 6)
  })

  it('没有顶层放置分支时安全跳过，不改任何轨道', () => {
    const upperTrack = new QuaternionKeyframeTrack(
      '.bones[上半身].quaternion', [0], [0, 0.1, 0, 0.995],
    )
    const clip = new Clip('', -1, [upperTrack])

    normalizeRootMotionInPlace(clip, fakeMesh())

    expect(clip.tracks).toHaveLength(1)
    expect(upperTrack.values[1]).toBeCloseTo(0.1, 6)
  })
})
