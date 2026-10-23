# Independent Julia reference, not a C++ binding and not a benchmark clock.
using Test
const FNV_PRIME=UInt64(1099511628211)
const FNV_OFFSET=UInt64(14695981039346656037)
function feed(h::UInt64,x::UInt32)
    for k=0:3
        h=(h ⊻ UInt64((x>>(8*k)) & 0xff))*FNV_PRIME
    end
    h
end
# Independent binary min-heap ordered by (time, row-major cell, emitter).
function pushheap!(heap, item)
    push!(heap,item)
    i=length(heap)
    while i>1
        p=i÷2
        isless(heap[i],heap[p]) || break
        heap[i],heap[p]=heap[p],heap[i]
        i=p
    end
end
function popheap!(heap)
    first=heap[1]
    tail=pop!(heap)
    if !isempty(heap)
        heap[1]=tail
        i=1
        while 2*i<=length(heap)
            c=2*i
            if c<length(heap) && isless(heap[c+1],heap[c])
                c+=1
            end
            isless(heap[c],heap[i]) || break
            heap[c],heap[i]=heap[i],heap[c]
            i=c
        end
    end
    first
end
function independent(width)
    cells=width*width
    owners=fill(UInt32(7),cells)
    owners[1]=owners[end]=0
    done=falses(cells)
    rgba=fill((96,40,128,255),cells)
    seed=UInt32((width÷2)*width+width÷2)
    heap=Tuple{Float64,UInt32,UInt32}[]
    pushheap!(heap,(0.,seed,seed))
    events=NamedTuple[]
    refusals=UInt64(0)
    hash=FNV_OFFSET
    tinted=0
    evaluations=0
    while !isempty(heap)
        time,cell,emitter=popheap!(heap)
        if done[Int(cell)+1]
            refusals+=1
            continue
        end
        x=Int(cell)%width; y=Int(cell)÷width
        px=Int(emitter)%width; py=Int(emitter)÷width
        factor=1.
        if cell!=emitter
            dx=x-px;dy=y-py
            radial=30*dx/hypot(dx,dy)
            factor=120/(120-radial)
            evaluations+=1
        end
        changed=0
        ix=Int(cell)+1
        if owners[ix]!=0 && cell!=emitter
            tint=clamp(factor-1.,-1.,1.)
            amount=floor(Int,abs(tint)*64+0.5)
            r,g,b,a=rgba[ix]
            if tint>0
                rgba[ix]=(max(0,r-amount),g,min(255,b+amount),a)
            elseif tint<0
                rgba[ix]=(min(255,r+amount),g,max(0,b-amount),a)
            end
            changed=rgba[ix]!=(r,g,b,a) ? 1 : 0
            evaluations+=1
        end
        done[ix]=true
        tinted+=changed
        event=(cell=cell,emitter=emitter,time=time,factor=factor,
               owner=owners[ix],tinted=changed,rgba=rgba[ix])
        push!(events,event)
        for v in (cell,emitter,owners[ix],UInt32(changed))
            hash=feed(hash,v)
        end
        for dy=-1:1,dx=-1:1
            dx==0 && dy==0 && continue
            xx=x+dx;yy=y+dy
            if xx<0 || yy<0 || xx>=width || yy>=width
                continue
            end
            neighbor=UInt32(yy*width+xx)
            if !done[Int(neighbor)+1]
                d=(dx!=0 && dy!=0) ? 1.4142135623730950488 : 1.
                pushheap!(heap,(time+d/120,neighbor,cell))
            else
                refusals+=1
            end
        end
    end
    (events=events,refusals=refusals,hash=hash,tinted=tinted,evaluations=evaluations)
end
function check(stdout)
    bywidth=Dict(64=>Vector{Vector{SubString{String}}}(),
                 128=>Vector{Vector{SubString{String}}}())
    meta=Dict{Int,Vector{SubString{String}}}()
    for line in split(chomp(stdout),'\n')
        row=split(line,'\t')
        length(row)>2 || error("unexpected native line")
        width=parse(Int,row[2])
        @test haskey(bywidth,width)
        if row[1]=="W"
            push!(bywidth[width],row)
        elseif row[1]=="M"
            @test !haskey(meta,width)
            meta[width]=row
        else
            error("unrecognized native receipt")
        end
    end
    @testset "independent full 64/128 C++ Julia events" begin
        @test length(meta)==2
        for width in (64,128)
            expected=independent(width)
            rows=bywidth[width]
            @test length(rows)==width*width
            @test length(expected.events)==width*width
            for (row,event) in zip(rows,expected.events)
                @test length(row)==12
                @test parse(UInt32,row[3])==event.cell
                @test parse(UInt32,row[4])==event.emitter
                @test isapprox(parse(Float64,row[5]),event.time;rtol=2e-14,atol=1e-14)
                @test isapprox(parse(Float64,row[6]),event.factor;rtol=2e-14,atol=1e-14)
                @test parse(UInt32,row[7])==event.owner
                @test parse(Int,row[8])==event.tinted
                @test ntuple(k->parse(Int,row[8+k]),4)==event.rgba
            end
            row=meta[width]
            @test parse(UInt64,row[3])==expected.refusals
            @test parse(UInt64,row[4])==expected.hash
            @test parse(Int,row[5])==expected.tinted
            @test parse(Int,row[6])==expected.evaluations
            @test parse(Int,row[7])<=expected.evaluations
            println("JULIA_GRID_PARITY_PASS width=$width cells=$(width*width) hash=$(expected.hash)")
        end
    end
end
length(ARGS)==1 || error("usage: julia spherepop_grid128_julia_oracle.jl compiled-binary")
check(read(Cmd([abspath(ARGS[1])]),String))
